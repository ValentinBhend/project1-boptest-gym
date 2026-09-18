'''Talk to a BOPTEST test case served by bridge.server.

Interchangeable with BoptestClient, so BoptestGymEnv needs no knowledge of it,
and written against the standard library alone: the process running the agent
never imports pyfmi, BOPTEST's numpy pin, or anything linking libgfortran.

    from bridge import BridgeClient
    env = BoptestGymEnv(testcase='bestest_hydronic_heat_pump',
                        client=BridgeClient(testcase='bestest_hydronic_heat_pump'),
                        ...)

'''

import atexit
import os
import socket
import time

from .wire import recv, send

DEFAULT_URL = os.environ.get('BOPTEST_BRIDGE_URL', '127.0.0.1:5000')

# Calls whose answer holds until the simulation moves on, and so can be fetched
# in the same round trip as the advance before them.
PREFETCHABLE = (('get', 'kpi'), ('put', 'forecast'))

# Calls that move the simulation, after which anything cached is stale.
MOVES = (('put', 'initialize'), ('put', 'step'), ('put', 'scenario'))


class BridgeClient(object):

    def __init__(self, url=None, testcase=None, select_options=None,
                 timeout=300.0, prefetch=True):
        self.url = url or DEFAULT_URL
        self._prefetch = prefetch
        self._plan = []
        self._cache = {}
        self._kpi_subset_supported = True
        self._sock = None
        self.calls = 0

        host, _, port = self.url.rpartition(':')
        host = (host or '127.0.0.1').replace('http://', '').strip('/')
        self._sock = self._connect(host, int(port), timeout)
        send(self._sock,
             {'op': 'select', 'testcase': testcase, 'options': select_options or {}})
        reply = recv(self._sock)
        if 'error' in reply:
            raise RuntimeError('BOPTEST could not start {0!r}: {1}'
                               .format(testcase, reply['error']))
        self.testid = reply['testid']
        atexit.register(self.stop)

    @staticmethod
    def _connect(host, port, timeout):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                sock = socket.create_connection((host, port), timeout=timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return sock
            except OSError as exc:
                last = exc
                time.sleep(0.05)
        raise RuntimeError('No BOPTEST bridge at {0}:{1} after {2}s: {3}. Start '
                           'one with:  docker compose -f bridge/compose.yml up'
                           .format(host, port, timeout, last))

    def _rpc(self, calls):
        self.calls += 1
        send(self._sock, calls)
        return recv(self._sock)

    @staticmethod
    def _payload(endpoint, result):
        status, message, payload = result
        if status != 200:
            raise RuntimeError('BOPTEST "{0}" failed with status {1}: {2}'
                               .format(endpoint, status, message))
        return payload

    def _call(self, method, endpoint, payload):
        if (method, endpoint) in MOVES:
            self._cache = {}
            if endpoint == 'initialize':
                self._plan = []
        else:
            self._plan.append((method, endpoint, payload))
        key = (method, endpoint, _freeze(payload))
        if key in self._cache:
            return self._cache.pop(key)
        return self._payload(endpoint, self._rpc([(method, endpoint, payload)])[0])

    def _advance(self, inputs):
        '''Advance, bringing back whatever the last step went on to ask for.'''

        extras, seen = [], set()
        if self._prefetch:
            for method, endpoint, payload in self._plan:
                key = (method, endpoint, _freeze(payload))
                if (method, endpoint) in PREFETCHABLE and key not in seen:
                    seen.add(key)
                    extras.append((method, endpoint, payload))
        results = self._rpc([('post', 'advance', inputs)] + extras)
        self._cache = {(m, e, _freeze(p)): self._payload(e, r)
                       for (m, e, p), r in zip(extras, results[1:])}
        self._plan = []
        return self._payload('advance', results[0])

    # --- the BoptestClient interface ----------------------------------------
    def get(self, endpoint, params=None):
        params = dict(params or {})
        if endpoint == 'kpi':
            names = params.get('names')
            if isinstance(names, str):
                names = [n for n in names.split(',') if n]
            params = {'names': list(names) if names else None}
        return self._call('get', endpoint, params)

    def put(self, endpoint, json=None):
        return self._call('put', endpoint, json or {})

    def post(self, endpoint, json=None):
        if endpoint == 'advance':
            return self._advance(json or {})
        return self._call('post', endpoint, json or {})

    def kpis(self, names=None):
        return self.get('kpi', {'names': list(names) if names else None})

    def stop(self):
        '''Close the connection, which ends the test case's process.'''

        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


def _freeze(obj):
    if isinstance(obj, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in obj.items()))
    if isinstance(obj, (list, tuple)):
        return tuple(_freeze(x) for x in obj)
    return obj
