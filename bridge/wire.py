'''Framing for the messages between an environment and its test case.

A frame is a four byte little-endian length followed by a json object.  json
rather than pickle because the server listens on a port: pickle would let
anything able to reach it run code in the worker, and it measured about 1%
faster.

'''

import json
import struct


def send(sock, obj):
    raw = json.dumps(obj).encode()
    sock.sendall(struct.pack('<I', len(raw)) + raw)


def recv(sock):
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
    return json.loads(b''.join(parts))
