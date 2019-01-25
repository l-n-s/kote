import asyncio
import logging
import time
import os
from contextlib import suppress
import re
from collections import deque

import i2plib.utils

from kote.fs import get_datadir
from kote.protocol import Message
from kote.core import KoteCore, current_task

SERVER_NAME = "kote"
REPLY_PREFIX = ":{} ".format(SERVER_NAME).encode()
DEFAULT_CHANNELS = ["#contacts", "#public"]

linesep_regexp = re.compile(r"\r?\n")
valid_nickname_regexp = re.compile(
    r"^[][\`_^{|}A-Za-z][][\`_^{|}A-Za-z0-9-]{0,50}$")
valid_channelname_regexp = re.compile(
    r"^[&#+!][^\x00\x07\x0a\x0d ,:]{0,50}$")

HELP_TEXT = ["Available commands:", "add [nick:address]", "del [nick]", 
    "online", "list"]

def parse_read_buffer(data):
    """Parse data received from the IRC client"""
    commands = []
    lines = linesep_regexp.split(data.decode().strip())

    for line in lines:
        if not line: continue
        x = line.split(" ", 1)
        command = x[0].upper()
        if len(x) == 1:
            arguments = []
        else:
            if len(x[1]) > 0 and x[1][0] == ":":
                arguments = [x[1][1:]]
            else:
                y = x[1].split(" :", 1)
                arguments = y[0].split()
                if len(y) == 2:
                    arguments.append(y[1])
        commands.append((command, arguments))

    return commands

async def irc_broadcast(clients, msg, skip=None):
    """Broadcast IRC command to all real IRC clients"""
    for client in list(clients.values()):
        if skip and client == skip:
            continue
        await client.message(msg)

async def irc_privmsg(nick, clients, msg, target=None, skip=None):
    """Broadcast PRIVMSG to all real IRC clients"""
    if "!" not in nick: nick = "{}!{}@kote".format(nick, nick)
    for client in list(clients.values()):
        if skip and client == skip:
            continue

        _target = target if target else client.nickname
        await client.message(":{} PRIVMSG {} :{}".format(nick, _target, msg))


class Client:
    def __init__(self, kote, reader, writer, handler_task):
        self.kote = kote
        self.reader = reader
        self.writer = writer
        self.handler_task = handler_task
        self.timestamp = time.time()
        self.nickname = None
        self.user = None
        self.realname = None
        self.joined_channels = False
        self.sent_ping = False
        (self.host, self.port) = self.writer.get_extra_info("peername")
        logging.debug("client created: "+self.host + " " + str(self.port))

    @property
    def prefix(self):
        return "{}!{}@kote".format(self.nickname, self.user)

    def channel_members(self, chan):
        members = list(self.kote.clients) + list(self.kote.addressbook.keys())
        if chan == "#contacts": members.append("ContactsBot")
        return members

    async def message(self, msg):
        self.writer.write(msg.encode() + b"\r\n")

    async def reply(self, msg):
        self.writer.write(REPLY_PREFIX + msg.encode() + b"\r\n")

    async def reply_403(self, channel):
        await self.reply("403 {} {} :No such channel".format(self.nickname, channel))

    async def reply_461(self, command):
        nickname = self.nickname or "*"
        await self.reply("461 {} {} :Not enough parameters".format(nickname, command))

    async def check_aliveness(self):
        """Ping and return False if client is inactive for a long time"""
        now = time.time()
        if self.timestamp + 180 < now:
            return False
        elif not self.sent_ping and self.timestamp + 90 < now:
            if self.nickname and self.user:
                await self.message("PING :"+SERVER_NAME)
                self.sent_ping = True
            else:
                return False
        return True

    async def disconnect(self):
        """Disconnect IRC client"""
        logging.debug("disconnecting")

        self.writer.close()
        if self.nickname and self.user:
            if self.nickname in self.kote.clients:
                del self.kote.clients[self.nickname]
            await irc_broadcast(self.kote.clients, 
                    ":{} QUIT :".format(self.prefix), skip=self)

    async def send_names(self, arguments):
        """is sent when the channel is joined"""
        if len(arguments) > 0:
            channelnames = arguments[0].split(",")
        else:
            channelnames = sorted(DEFAULT_CHANNELS)
        if len(arguments) > 1:
            keys = arguments[1].split(",")
        else:
            keys = []
        keys.extend((len(channelnames) - len(keys)) * [None])
        for (i, channelname) in enumerate(channelnames):
            if not valid_channelname_regexp.match(channelname) \
                    or channelname not in DEFAULT_CHANNELS:
                await self.reply_403(channelname)
                continue

            await irc_broadcast(self.kote.clients, 
                    ":{} JOIN {}".format(self.prefix, channelname))
            if channelname == "#contacts": 
                topic = "Manage contacts here. Type HELP for assistance"
            elif channelname == "#public":
                topic = "Broadcast messages to all of your peers"
            await self.reply("332 {} {} :{}".format(self.nickname, channelname,
                topic))
            names_prefix = "353 {} = {} :".format(self.nickname, channelname)
            names = ""
            # Max length: reply prefix ":server_name(space)" plus CRLF in
            # the end.
            names_max_len = 512 - (len(SERVER_NAME) + 2 + 2)

            for name in sorted(self.channel_members(channelname)):
                if not names:
                    names = names_prefix + name
                # Using >= to include the space between "names" and "name".
                elif len(names) + len(name) >= names_max_len:
                    await self.reply(names)
                    names = names_prefix + name
                else:
                    names += " " + name
            if names:
                await self.reply(names)
            await self.reply("366 {} {} :End of NAMES list".format(
                self.nickname, channelname))
            self.joined_channels = True


    async def who_handler(self, arguments):
        return
        if len(arguments) == 1:
            targetname = arguments[0]
            if targetname in DEFAULT_CHANNELS:
                for m in self.channel_members(targetname):
                    if m in self.kote.addressbook.keys():
                        realname = host = self.kote.addressbook[m]
                    else:
                        realname, host = "", "kote"
                        
                    await self.reply("352 {} {} {} {} {} {} H :0 {}".format(
                          self.nickname, targetname, m, host, SERVER_NAME,
                          m, realname))
                await self.reply("315 {} {} :End of WHO list".format(
                           self.nickname, targetname))

    async def whois_handler(self, arguments):
        """WHOIS command"""
        if len(arguments) > 1:
            name = arguments[0]
            if name in self.kote.addressbook.keys():
                await self.reply("311 {} {} {} {} * :{}".format(self.nickname, 
                    name, name, self.kote.addressbook[name], self.kote.addressbook[name]))
                await self.reply("312 {} {} {} :{}".format(self.nickname, 
                    name, SERVER_NAME, SERVER_NAME))
                await self.reply("319 {} {} :{}".format(self.nickname, name,
                              "".join(x + " " for x in DEFAULT_CHANNELS)))
                await self.reply("318 {} {} :End of WHOIS list".format(
                    self.nickname, name))

    async def nick_handler(self, arguments):
        """NICK command"""
        if len(arguments) < 1:
            await self.reply("431 :No nickname given")
        else:
            newnick = arguments[0]
            if newnick == self.nickname:
                pass
            elif newnick in self.kote.clients:
                await self.reply("433 {} {} :Nickname is already in use".format(
                    self.nickname, newnick))
            elif not valid_nickname_regexp.match(newnick):
                await self.reply("432 {} {} :Erroneous Nickname".format(
                    self.nickname, newnick))
            else:
                oldnickname = self.nickname
                self.nickname = newnick
                del self.kote.clients[oldnickname]
                self.kote.clients[self.nickname] = self
                await irc_broadcast(self.kote.clients, 
                        ":{}!{}@kote NICK {}".format(
                            oldnickname, self.user, self.nickname))


    async def privmsg_handler(self, arguments):
        """PRIVMSG command"""
        if len(arguments) == 0:
            await self.reply("411 {} :No recipient given (PRIVMSG)".format(
                self.nickname))
        elif len(arguments) == 1:
            await self.reply("412 {} :No text to send".format(self.nickname))
        else:
            target, message = arguments
            if target in DEFAULT_CHANNELS:
                await irc_privmsg(self.prefix, self.kote.clients, message, 
                        target=target, skip=self)
                if target == "#public":
                    await self.public_message_handler(message)
                elif target == "#contacts":
                    await self.contacts_message_handler(message)
            elif target in self.kote.addressbook.keys():
                await self.kote.send_message(Message(code=Message.PRIVATE, 
                            destination=self.kote.addressbook[target],
                            content=message))

    async def public_message_handler(self, message):
        """Handle #public message"""
        for d in self.kote.addressbook.humans():
            await self.kote.send_message(Message(
                    code=Message.PUBLIC, destination=d, content=message))

    async def contacts_message_handler(self, message):
        """Handle #contacts message"""
        command = message.split()
        if command[0].lower() == "help":
            for m in HELP_TEXT:
                await irc_privmsg("ContactsBot", self.kote.clients, m, 
                        "#contacts")
            await irc_privmsg("ContactsBot", self.kote.clients, 
                    "Your address --> {}:{}".format(self.nickname,
                        self.kote.destination.base32), 
                    "#contacts")
        elif command[0].lower() == "add" and len(command) == 2:
            try:
                name, address = command[1].split(":")
            except ValueError:
                return

            await self.add_contact(name, address, self.nickname)
        elif command[0].lower() == "del" and len(command) == 2:
            await self.remove_contact(command[1])
        elif command[0].lower() == "online":
            names = [self.kote.addressbook.get_name(a) for a in \
                        self.kote.addressbook.online_peers()]
            for n in names:
                if n:
                    await irc_privmsg(self.kote.contact_prefix(n), self.kote.clients, 
                            "\x01ACTION online\x01", "#contacts")
        elif command[0].lower() == "list":
            for a in self.kote.addressbook.values():
                await irc_privmsg("ContactsBot", self.kote.clients, 
                        "{}:{} last seen: {}".format(
                            self.kote.addressbook.get_name(a), a,
                            self.kote.addressbook.last_seen(a)), "#contacts")


    async def add_contact(self, name, address, your_name):
        if name and valid_nickname_regexp.match(name) \
                and name not in self.kote.clients:
            added = await self.kote.add_contact(name, address, your_name)
            if added:
                prefix = self.kote.contact_prefix(name)
                for chan in DEFAULT_CHANNELS:
                    await irc_broadcast(self.kote.clients, 
                            ":{} JOIN {}".format(prefix, chan))


    async def remove_contact(self, name):
        prefix = self.kote.contact_prefix(name)
        removed = await self.kote.remove_contact(name)
        if removed:
            await irc_broadcast(self.kote.clients, ":{} QUIT :".format(prefix))

    async def command_handler(self, command, arguments):
        if command == "JOIN":
            if len(arguments) < 1:
                await self.reply_461("JOIN")
            else:
                if not self.joined_channels:
                    await self.send_names(arguments)
        elif command == "NICK":
            await self.nick_handler(arguments)
        elif command == "WHOIS":
            await self.whois_handler(arguments)
        elif command == "WHO":
            await self.who_handler(arguments)
        elif command == "PRIVMSG":
            await self.privmsg_handler(arguments)

    async def registration_handler(self, command, arguments):
        if command == "NICK":
            if len(arguments) < 1:
                await self.reply("431 :No nickname given")
            else:
                nick = arguments[0]
                if nick in self.kote.clients.keys():
                    await self.reply("433 * {} :Nickname is already in use".format(nick))
                elif not valid_nickname_regexp.match(nick):
                    await self.reply("432 * {} :Erroneous nickname".format(nick))
                else:
                    self.nickname = nick
        elif command == "USER":
            if len(arguments) < 4:
                await self.reply_461("USER")
            else:
                self.user = arguments[0]
                self.realname = arguments[3]

        if self.nickname and self.user:
            self.kote.clients[self.nickname] = self
            for m in ["001 {} :Hi, welcome to IRC", 
                    "002 {} :Your host is localhost, running version kote-1.0", 
                    "003 {} :This server was created sometime",
                    "004 {} localhost kote-1.0 o o", 
                    "251 {} :There are 1 users and 0 services on 1 server",
                    "422 {} :MOTD File is missing"]:
                await self.reply(m.format(self.nickname))

            await self.send_names(["#public,#contacts"])

            for scrollback, action in self.kote.scrollbacks.values():
                while scrollback:
                    self.kote.create_task(action(scrollback.popleft()))

class KoteIRC(KoteCore):
    def __init__(self, server_address, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_address = server_address
        self.clients = {}
        self.scrollbacks = {
            Message.PRIVATE: (deque(maxlen=1000), self.on_private_message),
            Message.PUBLIC: (deque(maxlen=1000), self.on_public_message),
            Message.AUTHORIZATION: (deque(maxlen=1000), self.on_authorization),
        }

    def contact_prefix(self, name):
        return "{}!{}@{}".format(name, name, self.addressbook[name])

    async def handle_irc_client(self, reader, writer):
        """IRC client connection handler"""
        with suppress(asyncio.CancelledError):
            c = Client(self, reader, writer, current_task(loop=self.loop))

            while True:
                data = await reader.read(512)

                if not data: break
                c.timestamp = time.time()
                c.sent_ping = False

                for command, arguments in parse_read_buffer(data):
                    logging.debug(command + str(arguments))
                    if command == "QUIT":
                        await c.disconnect()
                        return
                    elif command == "PING" and len(arguments) == 1:
                        await c.reply("PONG {} :{}".format(SERVER_NAME, arguments[0]))

                    if c.nickname and c.user:
                        await c.command_handler(command, arguments)
                    else:
                        await c.registration_handler(command, arguments)

            await c.disconnect()

    async def ping_pong(self):
        """Ping IRC clients and disconnect dead ones"""
        with suppress(asyncio.CancelledError):
            while True:
                dead = []
                for nick in list(self.clients.keys()):
                    with suppress(KeyError):
                        alive = await self.clients[nick].check_aliveness()
                        if not alive:
                            dead.append(nick)

                for nick in dead:
                    self.clients[nick].handler_task.cancel()
                    await self.clients[nick].disconnect()

                await asyncio.sleep(10)

    async def on_authorization(self, msg):
        if not self.clients:
            self.scrollbacks[Message.AUTHORIZATION][0].append(msg)
        elif valid_nickname_regexp.match(msg.content):
            if msg.name:
                await irc_privmsg(self.contact_prefix(msg.name), self.clients, 
                        "\x01ACTION authorization accepted\x01", "#contacts")
            else:
                await irc_privmsg("ContactsBot", self.clients, 
                        "Authorization request --> {}:{}".format(msg.content, 
                            msg.destination),
                        "#contacts")

    async def on_contact_online(self, name):
        await irc_privmsg(self.contact_prefix(name), self.clients, 
                "\x01ACTION is online\x01", "#contacts")

    async def on_private_message(self, msg):
        if not self.clients:
            self.scrollbacks[Message.PRIVATE][0].append(msg)
        else:
            for line in msg.content.split("\n"):
                await irc_privmsg(self.contact_prefix(msg.name), self.clients, line)

    async def on_public_message(self, msg):
        if not self.clients:
            self.scrollbacks[Message.PUBLIC][0].append(msg)
        else:
            for line in msg.content.split("\n"):
                await irc_privmsg(self.contact_prefix(msg.name), self.clients, line, 
                        target="#public")

    async def on_unauthorized(self, msg):
        await irc_privmsg(self.contact_prefix(msg.name), self.clients, 
                "\x01ACTION Authorization required\x01", "#contacts")

    async def start(self):
        """Start all tasks"""
        await super().start()

        self.irc_server_task = await asyncio.start_server(
                self.handle_irc_client, *self.server_address)
        self.ping_pong_task = self.create_task(self.ping_pong())
        logging.info("IRC server listening at: "+str(self.server_address))

    async def stop(self):
        """Stop all tasks"""
        for t in [self.ping_pong_task]:
            t.cancel()
            await t

        self.irc_server_task.close()
        await self.irc_server_task.wait_closed()
        await super().stop()

    def run_app(self):
        """App runner"""
        if i2plib.utils.is_address_accessible(self.server_address):
            logging.critical("Server is already running")
            return

        super().run_app()

def main():
    logging.basicConfig(
            level=logging.DEBUG if os.getenv("KOTE_DEBUG") else logging.INFO)

    server_address = i2plib.utils.address_from_string(
            os.getenv("KOTE_IRC_ADDRESS", "127.0.0.1:17772"))

    app = KoteIRC(server_address, get_datadir(), i2plib.utils.get_sam_address())
    if os.getenv("KOTE_IRC_IGNORE_UNAUTHORIZED"):
        app.ignore_unauthorized = True
    app.run_app()

if __name__ == "__main__":
    main()
