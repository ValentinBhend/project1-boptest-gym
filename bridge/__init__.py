'''An out-of-process backend for BoptestGymEnv.

The test case runs in its own process, served on a port by ``bridge.server``;
the environment holds a socket and needs only the standard library to use it.
See Note 4 in the README.

'''

from .client import BridgeClient

__all__ = ['BridgeClient']
