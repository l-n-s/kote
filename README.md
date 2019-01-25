kote
====

<img height="200px" src="https://raw.githubusercontent.com/l-n-s/kote/master/images/kote.png">

Invisible Messaging

What is it?
-----------

- Dead simple text-based messenger
- 100% decentralized and distributed
- Works on top of [Invisible Internet](https://en.wikipedia.org/wiki/I2P), so all communications are encrypted and anonymous

Features
--------

- Contact authorization
- Private messaging
- Broadcast message to all contacts (like twitter)
- Runs a local IRC server, use your favorite IRC client as a front-end
- API for building bots in Python

Requirements
------------

- Python version >= 3.5
- I2P router with SAM API enabled ([i2pd](https://i2pd.website) or [Java I2P](https://geti2p.net/_static/images/enable-sam.jpeg))

Installation
------------

Download a release tarball and unpack it.

Alternatively, use pip:

    pip3 install https://github.com/l-n-s/kote/zipball/master

Usage
-----

If you've installed kote with pip, run with `kote-irc` command.

If you are using the release tarball, unpack it and run `./kote-irc` in the source directory.

kote will start a local IRC server at 127.0.0.1:17772, which you can use with your favorite IRC client.
Navigate to #contacts channel and type HELP there.

Configuring
-----------

kote can be configured by setting the following environment variables:

- KOTE\_DATADIR - a directory, where kote stores it's files. 
  By default, it's `$HOME/.config/kote` in Linux and `%APPDATA%\kote` in Windows.
- KOTE\_IRC\_ADDRESS - HOST:PORT for the local IRC server, `127.0.0.1:17772` by default. 
