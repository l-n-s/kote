from uuid import UUID, uuid4

MAX_MESSAGE_LENGTH = 1024 # 1 byte for code, 16 for UUID, 1007 for content

class ValidationError(Exception):
    pass

class Message:
    AUTHORIZATION = 1
    PING          = 2
    PRIVATE       = 3
    PUBLIC        = 4
    OK            = 5
    UNAUTHORIZED  = 6

    def __init__(self, code=None, uuid=None, content="", destination=None, \
                 name=None):
        self.code = code
        self.uuid = uuid or uuid4()
        self.content = content
        self.destination = destination
        self.name = name

    def __bytes__(self):
        """Convert the message to bytes string"""
        return bytes([self.code]) + self.uuid.bytes + self.content.encode()

    def __repr__(self):
        return "Message(code={}, uuid={}, content={}, destination={}, name={})".format(
                self.code, str(self.uuid), self.content, self.destination, self.name)

    @classmethod
    def valid_code(cls, code):
        """Check if code is valid"""
        return code in [cls.AUTHORIZATION, cls.PING, cls.PRIVATE, cls.PUBLIC, 
                        cls.OK, cls.UNAUTHORIZED]

    @classmethod
    def parse(cls, data, destination):
        """Parse binary data and return a message"""
        data_length = len(data)

        if data_length < 17 or data_length > MAX_MESSAGE_LENGTH:
            raise ValidationError("invalid message size: "+str(data_length))

        code, uuid, content = int(data[0]), data[1:17], ""
        if not cls.valid_code(code):
            raise ValidationError("invalid code")

        uuid = UUID(bytes=uuid)

        if data_length > 17:
            try:
                content = data[17:].decode()
            except UnicodeError:
                raise ValidationError("content is not a valid unicode string")

        return cls(code=code, uuid=uuid, content=content, 
                   destination=destination)

