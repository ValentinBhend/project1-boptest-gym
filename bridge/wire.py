'''Framing for the messages between an environment and its test case.

A frame is a four byte little-endian length followed by an encoded object.
json is the default because the server listens on a port: pickle would let
anything able to reach that port run code in the worker.

'''

import json
import pickle
import struct


class JsonCodec(object):
    name = 'json'
    encode = staticmethod(lambda obj: json.dumps(obj).encode())
    decode = staticmethod(lambda raw: json.loads(raw))


class PickleCodec(object):
    '''Faster by about 1%, and unsafe against anything you do not trust.'''

    name = 'pickle'
    encode = staticmethod(lambda obj: pickle.dumps(obj, protocol=4))
    decode = staticmethod(pickle.loads)


CODECS = {'json': JsonCodec, 'pickle': PickleCodec}


def send(sock, codec, obj):
    raw = codec.encode(obj)
    sock.sendall(struct.pack('<I', len(raw)) + raw)


def recv(sock, codec):
    head = b''
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk:
            raise EOFError('connection closed')
        head += chunk
    size = struct.unpack('<I', head)[0]
    parts = []
    got = 0
    while got < size:
        chunk = sock.recv(size - got)
        if not chunk:
            raise EOFError('connection closed mid frame')
        parts.append(chunk)
        got += len(chunk)
    return codec.decode(b''.join(parts))
