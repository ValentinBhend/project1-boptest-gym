'''Talk to a BOPTEST test case served by bridge.server.

Interchangeable with BoptestClient, so BoptestGymEnv needs no knowledge of it,
and written against the standard library alone: the process running the agent
never imports pyfmi, BOPTEST's numpy pin, or anything that links
libgfortran.so.4.

    from bridge import BridgeClient
    env = BoptestGymEnv(testcase='bestest_hydronic_heat_pump',
                        client=BridgeClient(testcase='bestest_hydronic_heat_pump'),
                        ...)

'''

import atexit
import os
import socket
import time

from .wire import CODECS, recv, send

DEFAULT_URL = os.environ.get('BOPTEST_BRIDGE_URL', '127.0.0.1:5000')

# Results that stay valid until the simulation moves on, and so can be fetched
# in the same round trip as the advance that precedes them.
PREFETCHABLE = ('kpi', 'forecast')


class BridgeClient(object):

    def __init__(self, url=None, testcase=None, select_options=None,
                 codec='json', timeout=300.0, prefetch=True):
        self.url = url or DEFAULT_URL
        self._codec = CODECS[codec]
        self._prefetch = prefetch
        self._plan = []
        self._cache = {}
        self._kpi_subset_supported = True
        self._sock = None
        self.calls = 0

        host, _, port = self.url.rpartition(':')
        host = (host or '127.0.0.1').replace('http://', '').strip('/')
        self._sock = self._connect(host, int(port), timeout)
        send(self._sock, self._codec,
             {'op': 'select', 'testcase': testcase,
              'options': select_options or {}})
        reply = recv(self._sock, self._codec)
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

    # --- transport ----------------------------------------------------------
    def _rpc(self, ops):
        self.calls += 1
        send(self._sock, self._codec, ops)
        return recv(self._sock, self._codec)

    @staticmethod
    def _payload(endpoint, result):
        status, message, payload = result
        if status != 200:
            raise RuntimeError('BOPTEST "{0}" failed with status {1}: {2}'
                               .format(endpoint, status, message))
        return payload

    def _call(self, op, args):
        if op not in ('advance', 'initialize'):
            self._plan.append((op, args))
        key = (op, _freeze(args))
        if key in self._cache:
            return self._cache.pop(key)
        return self._payload(op, self._rpc([(op, args)])[0])

    def _advance(self, inputs):
        '''Advance, bringing back whatever the last step went on to ask for.'''

        ops = [('advance', inputs)]
        extras = []
        if self._prefetch:
            seen = set()
            for op, args in self._plan:
                key = (op, _freeze(args))
                if op in PREFETCHABLE and key not in seen:
                    seen.add(key)
                    extras.append((op, args))
        results = self._rpc(ops + extras)
        self._cache = {(op, _freeze(args)): self._payload(op, result)
                       for (op, args), result in zip(extras, results[1:])}
        self._plan = []
        return self._payload('advance', results[0])

    # --- the BoptestClient interface ----------------------------------------
    def get(self, endpoint, params=None):
        if endpoint == 'kpi':
            names = None
            if params and params.get('names'):
                names = [n for n in str(params['names']).split(',') if n]
            return self._call('kpi', {'names': names})
        return self._call({'name': 'name', 'measurements': 'measurements',
                           'inputs': 'inputs', 'forecast_points': 'forecast_points',
                           'step': 'get_step', 'scenario': 'get_scenario',
                           'version': 'version'}[endpoint], {})

    def put(self, endpoint, json=None):
        json = json or {}
        if endpoint in ('initialize', 'step', 'scenario'):
            self._cache = {}
            if endpoint == 'initialize':
                self._plan = []
            return self._call(endpoint, json)
        if endpoint in ('results', 'forecast'):
            return self._call(endpoint, json)
        raise ValueError('Unsupported PUT endpoint "{0}"'.format(endpoint))

    def post(self, endpoint, json=None):
        if endpoint == 'advance':
            return self._advance(json or {})
        raise ValueError('Unsupported POST endpoint "{0}"'.format(endpoint))

    def kpis(self, names=None):
        return self._call('kpi', {'names': list(names) if names else None})

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
