'''Serve BOPTEST test cases on a port, one process per test case.

    python -m bridge.server --boptest-root /boptest

Accepts a connection, forks, and lets the child run one test case for as long
as that connection lasts.  Nothing has to be reaped: an agent that crashes
closes its connection, and the kernel says so.

The parent never loads an FMU, so the one-test-case-per-process rule is kept by
construction however many environments connect.

'''

import argparse
import logging
import os
import signal
import socket
import sys

from .case import TestCaseRunner
from .wire import recv, send


def serve_one(conn, boptest_root):
    '''Run one test case for one connection, then exit.'''

    runner = None
    try:
        request = recv(conn)
        if request.get('op') != 'select':
            send(conn, {'error': 'expected select, got %r' % request.get('op')})
            return
        runner = TestCaseRunner(boptest_root, request['testcase'],
                                request.get('testcase_dir'),
                                request.get('options'))
        send(conn, {'testid': str(os.getpid())})
        while True:
            try:
                calls = recv(conn)
            except EOFError:
                return
            send(conn, runner.batch(calls))
    except EOFError:
        return
    except Exception as exc:
        try:
            send(conn, {'error': '{0}: {1}'.format(type(exc).__name__, exc)})
        except Exception:
            pass
    finally:
        if runner is not None:
            runner.close()
        try:
            conn.close()
        except Exception:
            pass


def serve(host, port, boptest_root):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(64)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)   # no zombies to collect
    sys.stderr.write('BRIDGE READY {0}:{1}\n'.format(host, port))
    sys.stderr.flush()
    while True:
        conn, _ = listener.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if os.fork() == 0:
            listener.close()
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            serve_one(conn, boptest_root)
            os._exit(0)
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='bridge.server', description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int,
                        default=int(os.environ.get('BOPTEST_BRIDGE_PORT', 5000)))
    parser.add_argument('--boptest-root', default=os.environ.get('BOPTEST_ROOT'))
    args = parser.parse_args(argv)
    if not args.boptest_root:
        raise SystemExit('Set BOPTEST_ROOT or pass --boptest-root: the server '
                         'needs a BOPTEST tree holding the test case FMUs.')
    logging.disable(logging.CRITICAL)
    serve(args.host, args.port, args.boptest_root)


if __name__ == '__main__':
    main()
