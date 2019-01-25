import asyncio
import logging
from contextlib import suppress
import uuid

import i2plib.utils

from kote.fs import get_datadir
from kote.protocol import Message
from kote.core import KoteCore

ANNOYING_TEXT = "I'm the most annoying bot of this universe"

random_nickname = lambda: str(uuid.uuid4())[:8]

class EchoBot(KoteCore):

    async def annoying_notification(self):
        with suppress(asyncio.CancelledError):
            while True:
                messages = [Message(code=Message.PUBLIC, destination=d, \
                        content=ANNOYING_TEXT) for d in \
                            self.addressbook.online_peers()]
                for m in messages:
                    await self.send_message(m)

                await asyncio.sleep(120)
        
    async def on_authorization(self, msg):
        if msg.destination not in self.addressbook.values():
            await self.add_contact(random_nickname(), msg.destination, 
                    "EchoBot")

    async def on_unauthorized(self, msg):
        if msg.name:
            logging.debug("Removing from contacts: "+msg.name)
            await self.remove_contact(msg.name)

    async def on_private_message(self, msg):
        await self.send_message(Message(code=Message.PRIVATE, 
                                        destination=msg.destination,
                                        content=msg.content))

    async def start(self):
        """Start all tasks"""
        await super().start()
        self.annoy_task = self.create_task(self.annoying_notification())

    async def stop(self):
        """Stop all tasks"""
        for t in [self.annoy_task]:
            t.cancel()
            await t
        await super().stop()

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    app = EchoBot(get_datadir(), i2plib.utils.get_sam_address())
    app.run_app()
