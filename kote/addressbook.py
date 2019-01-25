import time
import datetime
import re

MAX_IDLE = 1800.0
VALID_BASE32_ADDRESS = re.compile(r"^([a-zA-Z0-9]{52})$")

class Addressbook:

    def __init__(self):
        self._NAME_ADDRESS_MAP = {}
        self._ADDRESS_NAME_MAP = {}
        self._ONLINE_MAP = {}

    def __str__(self):
        return str(self._NAME_ADDRESS_MAP)

    def __setitem__(self, name, address):
        if name in self._NAME_ADDRESS_MAP or address in self._ADDRESS_NAME_MAP:
            raise ValueError("Entry already exists")

        if not Addressbook.is_valid_address(address):
            raise ValueError("Invalid address")

        self._NAME_ADDRESS_MAP[name] = address
        self._ADDRESS_NAME_MAP[address] = name
        self._ONLINE_MAP[address] = None

    def __getitem__(self, name):
        return self._NAME_ADDRESS_MAP[name]

    def __delitem__(self, name):
        del self._ONLINE_MAP[self._NAME_ADDRESS_MAP[name]]
        del self._ADDRESS_NAME_MAP[self._NAME_ADDRESS_MAP[name]]
        del self._NAME_ADDRESS_MAP[name]

    def keys(self):
        return self._NAME_ADDRESS_MAP.keys()

    def values(self):
        return self._NAME_ADDRESS_MAP.values()

    def update(self, data):
        for k, v in data.items(): self[k] = v

    def get_name(self, address):
        if address in self._ADDRESS_NAME_MAP:
            return self._ADDRESS_NAME_MAP[address]
        else:
            return None

    def set_online(self, address):
        if address in self._ONLINE_MAP:
            self._ONLINE_MAP[address] = time.time()

    def last_seen(self, address):
        if address in self._ONLINE_MAP and self._ONLINE_MAP[address]: 
            ls = time.time() - self._ONLINE_MAP[address]
            return str(datetime.timedelta(seconds=ls)) + " ago"
        else:
            return "never"

    def is_online(self, address):
        """Check if a peer is online"""
        return address in self._ONLINE_MAP and \
            self._ONLINE_MAP[address] and \
            (time.time() - self._ONLINE_MAP[address]) < MAX_IDLE

    def online_peers(self):
        return [a for a in self.values() if self.is_online(a)]

    def humans(self):
        """Return only real contacts, not bots"""
        real = []
        for n in self._NAME_ADDRESS_MAP:
            if not n.endswith("Bot") and not n.endswith("_bot"): 
                real.append(self._NAME_ADDRESS_MAP[n])
        return real

    @classmethod
    def is_valid_address(cls, address):
        return bool(VALID_BASE32_ADDRESS.match(address))
