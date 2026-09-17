'''An out-of-process backend for BoptestGymEnv.

The test case runs in its own process, served on a port by ``bridge.server``;
the environment holds a socket and needs only the standard library to use it.
See Note 4 in the README.

'''

from .client import BridgeClient


def __getattr__(name):
    # ThreadVecEnv needs stable-baselines3; the client does not
    if name == 'ThreadVecEnv':
        from .vecenv import ThreadVecEnv
        return ThreadVecEnv
    raise AttributeError('module {0!r} has no attribute {1!r}'.format(__name__, name))


__all__ = ['BridgeClient', 'ThreadVecEnv']
