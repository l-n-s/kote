import os
import sys
import json

import i2plib

def get_datadir():
    if sys.platform == "win32":
        default_datadir = os.path.join(os.getenv("APPDATA"), "kote")
    elif sys.platform == "linux":
        confdir = os.getenv("XDG_CONFIG_HOME") or os.path.join(
                os.getenv("HOME"), ".config")
        default_datadir = os.path.join(confdir, "kote")
    else:
        default_datadir = "."

    return os.getenv("KOTE_DATADIR", default_datadir)

def read_file(path, mode="rb"):
    if os.path.exists(path):
        with open(path, mode) as f:
            data = f.read()
        return data

def write_file(path, data, mode="wb"):
    with open(path, mode) as f: f.write(data)

async def save_contacts(loop, contacts, datadir, filename="contacts.json"):
    """Write contacts to the disc"""
    await loop.run_in_executor(None, write_file, 
            os.path.join(datadir, filename), json.dumps(contacts), "w")

async def load_contacts(loop, datadir, filename="contacts.json"):
    """Read contacts from the disc"""
    data = await loop.run_in_executor(None, read_file, 
                        os.path.join(datadir, filename), "r")
    contacts = json.loads(data) if data else {}
    return contacts

async def load_destination(loop, sam_address, datadir, filename="kote.dat"):
    """Read destination from the disc OR create it"""
    path = os.path.join(datadir, filename)

    key_data = await loop.run_in_executor(None, read_file, path)
    if key_data:
        dest = i2plib.Destination(key_data, has_private_key=True)
    else:
        dest = await i2plib.new_destination(loop=loop, sam_address=sam_address)
        await loop.run_in_executor(None, write_file, path, 
                dest.private_key.data)

    return dest

