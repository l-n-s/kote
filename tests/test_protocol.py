from unittest import TestCase
from uuid import UUID

from kote.protocol import Message, ValidationError, MAX_MESSAGE_LENGTH

random_bytes = b'\x16\xdc#\x8aX\xe68\xde\xcd\xd2+\xe9c\x0c\x12\x9a'
dest = "5h4j3cmndwvitnh5y7nhg3bkzcvqvmlcwwmpsdiwadukzamwtejq"

class TestProtocol(TestCase):

    def test_valid(self):
        msg = Message(code=Message.PRIVATE, content="hello world!", 
                destination=dest)

        msg2 = Message.parse(bytes(msg), msg.destination)

        self.assertEqual(msg2.destination, msg.destination)
        self.assertEqual(bytes(msg2), bytes(msg))


        uuid = UUID(bytes=random_bytes)

        data = bytes([Message.AUTHORIZATION]) + random_bytes + "TestName".encode()

        msg = Message.parse(data, dest)
        msg2 = Message(code=Message.AUTHORIZATION, uuid=uuid, content="TestName")

        self.assertEqual(bytes(msg2), data)

    def test_invalid_length(self):
        data = b""
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)

        data = bytes([Message.PING])
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)

        data = bytes([Message.PING]) + random_bytes[:-1]
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)

        content = "a" * (MAX_MESSAGE_LENGTH - 17 + 1)
        data = bytes([Message.PING]) + random_bytes + content.encode()
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)


    def test_invalid_code(self):
        data = bytes([0]) + random_bytes + "test".encode()
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)


    def test_invalid_content(self):
        data = bytes([Message.PRIVATE]) + random_bytes + random_bytes
        with self.assertRaises(ValidationError):
            msg = Message.parse(data, dest)
