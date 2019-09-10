import asyncio
import sys
import os
import pathlib
from contextlib import suppress
from collections import deque
import random
import time
import uuid

import i2plib
import i2plib.utils

from kote.fs import load_contacts, save_contacts, load_destination
from kote.protocol import MAX_MESSAGE_LENGTH, Message, ValidationError
from kote.addressbook import Addressbook
from kote.log import logger

if sys.version_info.major == 3 and sys.version_info.minor < 7:
    all_tasks, current_task = asyncio.Task.all_tasks, asyncio.Task.current_task
else:
    all_tasks, current_task = asyncio.all_tasks, asyncio.current_task

async def cancel_pending_tasks(loop):
    for t in all_tasks(loop=loop):
        if t != current_task(loop=loop):
            try:
                t.cancel()
                await t
            except asyncio.CancelledError:
                logger.warning("Cancellation error: "+str(t))

SEND_RETRIES = 11
DEFAULT_TIMEOUT = 60
SESSION_RESTART_TIMEOUT = 30
PING_INTERVAL = 300

def gen_session_name(prefix="kote"):
    return "{}-{}".format(prefix, str(uuid.uuid4())[:6])

class MessageSender:
    def __init__(self, loop, task):
        self.loop = loop
        self.queue = asyncio.Queue(loop=self.loop)
        self.send = self.queue.put # shortcut
        self.task = asyncio.ensure_future(task(self.queue), loop=self.loop)
        self._stash = {
            Message.PRIVATE: deque(maxlen=1000),
            Message.PUBLIC: deque(maxlen=100),
            Message.AUTHORIZATION: deque(maxlen=10),
        }

    def stash(self, msg):
        """Add message to offline log"""
        if msg.code in self._stash: 
            self._stash[msg.code].append(msg)

    async def send_stash(self):
        """Send all messages from the offline log"""
        for q in self._stash.values():
            while q:
                await self.queue.put(q.popleft())

    async def stop(self):
        """Stop message sender"""
        self.task.cancel()
        await self.task

class KoteCore:
    def __init__(self, datadir, sam_address, session_name=None):
        self.datadir = datadir
        self.sam_address = sam_address
        self.loop = asyncio.get_event_loop()
        self.senders = {}
        self.online = asyncio.Event(loop=self.loop)
        self.destination = None
        self.session_reader = None
        self.session_writer = None
        self.addressbook = Addressbook()
        self.uuid_log = deque(maxlen=50)
        self.ignore_unauthorized = False
        self.session_name = session_name or gen_session_name()
        self.started_at = time.time()
        self.dest_cache = {}

    def create_task(self, fut):
        """Ensure future shortcut"""
        return asyncio.ensure_future(fut, loop=self.loop)

    async def add_contact(self, name, address, your_name):
        """Add contact to the addressbook and send auth request"""
        if address == self.destination.base32: return False

        try:
            self.addressbook[name] = address
        except ValueError as e:
            logger.error("Addressbook error: " + str(e))
            return False
        else:
            await save_contacts(self.loop, dict(self.addressbook), self.datadir)
            self.senders[address] = MessageSender(self.loop, self.sender)
            await self.senders[address].send(Message(code=Message.AUTHORIZATION,
                                destination=address, content=your_name))
            return True

    async def remove_contact(self, name):
        """Remove contact from the addressbook"""
        try:
            addr = self.addressbook[name]
        except KeyError as e:
            logger.error("Addressbook error: no such name " + str(e))
            return False
        else:
            await self.senders[addr].stop()
            del self.senders[addr]
            del self.addressbook[name]
            await save_contacts(self.loop, dict(self.addressbook), self.datadir)
            return True

    async def sam_session_loop(self):
        """Self-healing SAM session"""
        with suppress(asyncio.CancelledError):
            while True:
                try:
                    self.session_reader, self.session_writer = await \
                            i2plib.create_session(self.session_name, 
                                destination=self.destination, 
                                sam_address=self.sam_address, loop=self.loop)
                except (i2plib.DuplicatedDest):
                    logger.error("SAM destination already exists")
                except ConnectionError:
                    logger.error("SAM API is unavailable")
                else:
                    self.online.set()
                    logger.debug("SAM session is created: " \
                            + self.destination.base32)
                    await self.session_reader.read()
                    logger.error("SAM session is dead")
                    self.online.clear()

                logger.info("Restarting SAM session in {} seconds...".format(
                    SESSION_RESTART_TIMEOUT))
                await asyncio.sleep(SESSION_RESTART_TIMEOUT)

    async def pinger(self):
        """Send pings to all contacts if there are no online peers, or if 
        kote is running less than a 1/2 hour. Otherwise, ping online peers each 
        PING_INTERVAL and all peers each PING_INTERVAL * 6"""
        with suppress(asyncio.CancelledError):
            x = 0
            while True:
                await self.online.wait()
                # check expired peers
                for d in self.addressbook.get_expired_peers():
                    name = self.addressbook.get_name(d)
                    if name:
                        logger.debug("Peer %s goes offline", name)
                        self.addressbook.set_offline(d)
                        await self.on_contact_offline(name)

                if (time.time() - self.started_at) < 1800.0 \
                      or not self.addressbook.online_peers():
                    peers = self.addressbook.values()
                elif x == 6:
                    peers, x = self.addressbook.values(), 0
                else:
                    peers, x = self.addressbook.online_peers(), x + 1
                        
                for d in peers:
                    self.create_task(self._send_ping(d))
                await asyncio.sleep(PING_INTERVAL)

    async def _send_ping(self, destination):
        """One-shot ping message with a random delay"""
        with suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.sleep(random.choice(range(PING_INTERVAL)))

            data = await asyncio.wait_for(self._send_message( 
                    Message(code=Message.PING, destination=destination)), 
                    DEFAULT_TIMEOUT * 2)
            if data: 
                await self._dest_online(destination)

    async def sender(self, queue):
        """Message sender task"""
        with suppress(asyncio.CancelledError):
            while True:
                await self.online.wait()
                msg = await queue.get()
                delivered = False

                for x in range(SEND_RETRIES):
                    try:
                        data = await asyncio.wait_for(self._send_message(msg), 
                                DEFAULT_TIMEOUT)
                    except asyncio.TimeoutError:
                        pass
                    else:
                        if data:
                            try:
                                resp = Message.parse(data, msg.destination)
                            except ValidationError as e:
                                logger.warning(
                                    "Invalid response from {}: {}".format(
                                                msg.destination, e))
                            else:
                                delivered = True
                                await self._dest_online(msg.destination)
                                if resp.code == Message.OK:
                                    logger.debug(str(msg) + " delivered")
                                elif resp.code == Message.UNAUTHORIZED:
                                    logger.debug(str(msg) + " unauthorized")
                                    resp.name = self.addressbook.get_name(
                                            resp.destination)
                                    await self.on_unauthorized(resp)
                            break
                        else:
                            logger.debug(str(id(msg)) + " retrying")
                            await asyncio.sleep(DEFAULT_TIMEOUT / 2)

                if delivered:
                    logger.debug(str(msg) + " delivered, retries: " + str(x))
                else:
                    self.senders[msg.destination].stash(msg)

    async def _send_message(self, request):
        """Send message and receive response data"""
        data = b''
        await self.online.wait()

        try:
            if request.destination not in self.dest_cache:
                self.dest_cache[request.destination] = await i2plib.dest_lookup(
                            request.destination + ".b32.i2p", loop=self.loop, 
                            sam_address=self.sam_address)

            reader, writer = await i2plib.stream_connect(self.session_name, 
                    self.dest_cache[request.destination], loop=self.loop, 
                    sam_address=self.sam_address)
        except (i2plib.CantReachPeer, i2plib.InvalidKey, i2plib.Timeout, \
                i2plib.KeyNotFound, i2plib.PeerNotFound, i2plib.I2PError):
            logger.debug("Can't connect to {}".format(request.destination))
        except ConnectionError:
            logger.warning("_send_message fails: can't connect to SAM")
        else:
            writer.write(bytes(request))
            data = await reader.read(MAX_MESSAGE_LENGTH)
            writer.close()

        return data

    async def receiver(self):
        """Task to receive incoming messages from I2P"""
        with suppress(asyncio.CancelledError):
            while True:
                await self.online.wait()
                try:
                    reader, writer = await i2plib.stream_accept(
                            self.session_name,
                            sam_address=self.sam_address, loop=self.loop)
                except i2plib.I2PError:
                    logger.warning("Receiver fails: generic I2P error")
                except ConnectionError:
                    logger.warning("Receiver fails: can't connect to SAM")
                    await asyncio.sleep(SESSION_RESTART_TIMEOUT)
                else:
                    dest = await reader.readline()
                    if dest:
                        asyncio.ensure_future(
                                self._receive_message(reader, writer, dest), 
                                loop=self.loop)
                    else:
                        writer.close()

    async def _receive_message(self, reader, writer, destination):
        with suppress(asyncio.CancelledError):
            destination = i2plib.Destination(destination.decode())
            name = self.addressbook.get_name(destination.base32)
            if not name and self.ignore_unauthorized:
                writer.close()
                return

            try:
                data = await asyncio.wait_for(reader.read(MAX_MESSAGE_LENGTH), 
                                              DEFAULT_TIMEOUT)
            except asyncio.TimeoutError:
                writer.close()
                return

            try:
                request = Message.parse(data, destination.base32)
                request.name = name
            except ValidationError as e:
                logger.warning("Invalid request: "+str(e))
                writer.close()
                return

            if request.uuid.hex in self.uuid_log:
                logger.debug("Duplicate message: "+ str(request))
                writer.write(bytes(Message(code=Message.OK)))
                writer.close()
                return

            self.uuid_log.append(request.uuid.hex)
            logger.debug("Received message: " + str(request))


            if request.code == Message.PING \
                    or request.code == Message.AUTHORIZATION:
                writer.write(bytes(Message(code=Message.OK)))
                writer.close()

                if request.code == Message.PING:
                    await self.on_ping(request)
                elif request.code == Message.AUTHORIZATION:
                    await self.on_authorization(request)

            elif request.name:
                writer.write(bytes(Message(code=Message.OK)))
                writer.close()

                if request.code == Message.PRIVATE:
                    await self.on_private_message(request)
                elif request.code == Message.PUBLIC:
                    await self.on_public_message(request)
                elif request.code == Message.UNAUTHORIZED:
                    await self.on_unauthorized(request)
            else:
                writer.write(bytes(Message(code=Message.UNAUTHORIZED)))
                writer.close()
                return

            await self._dest_online(request.destination)

    async def _dest_online(self, destination):
        """Is triggered when any Message or data is received from the destination"""
        name = self.addressbook.get_name(destination)
        if name:
            if not self.addressbook.is_online(destination):
                logger.debug("Contact becomes online "+destination)
                await self.on_contact_online(name)
                await self.senders[destination].send_stash()
            self.addressbook.set_online(destination)

    async def start(self):
        """Start all tasks"""
        self.destination = await load_destination(self.loop, self.sam_address,
                self.datadir)

        c = await load_contacts(self.loop, self.datadir)
        self.addressbook.update(c)
        logger.debug("Contacts: " + str(self.addressbook))

        for address in self.addressbook.values():
            self.senders[address] = MessageSender(self.loop, self.sender)

        self.receiver_task = self.create_task(self.receiver())
        self.pinger_task = self.create_task(self.pinger())
        self.sam_session_loop_task = self.create_task(self.sam_session_loop())

    async def stop(self):
        """Stop all tasks"""
        self.online.clear()

        for t in self.senders.values():
            await t.stop()

        for t in [self.receiver_task, self.pinger_task,
                  self.sam_session_loop_task]:
            t.cancel()
            await t

    def run_app(self):
        """Application runner"""
        if not i2plib.utils.is_address_accessible(self.sam_address):
            logger.critical("SAM is unavailable")
            return

        if not os.path.exists(self.datadir):
            try:
                pathlib.Path(self.datadir).mkdir(mode=0o700, parents=True)
                logger.info("Created a new data directory: "+self.datadir)
            except PermissionError:
                logger.critical("Can't create data directory: "+self.datadir)
                return

        self.loop.run_until_complete(self.start())

        try:
            self.loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
        finally:
            self.loop.run_until_complete(self.stop())
            self.loop.run_until_complete(cancel_pending_tasks(self.loop))
            self.loop.stop()
            self.loop.close()

    async def send_message(self, msg):
        """Add Message to sender queue 
        Use this method only for authorized contacts!"""
        if self.addressbook.is_online(msg.destination):
            await self.senders[msg.destination].send(msg)
        else:
            self.senders[msg.destination].stash(msg)

    async def on_authorization(self, msg):
        """Is triggered when Message.AUTHORIZATION is received"""
        pass

    async def on_ping(self, msg):
        """Is triggered when Message.PING is received"""
        pass

    async def on_contact_online(self, name):
        """Is triggered when any Message is received and peer was offline"""
        pass

    async def on_contact_offline(self, name):
        """Is triggered when peer is marked as offline"""
        pass

    async def on_private_message(self, msg):
        """Is triggered when Message.PRIVATE is received"""
        pass

    async def on_public_message(self, msg):
        """Is triggered when Message.PUBLIC is received"""
        pass

    async def on_unauthorized(self, msg):
        """Is triggered when Message.UNAUTHORIZED is received"""
        pass
