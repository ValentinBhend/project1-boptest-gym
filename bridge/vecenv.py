'''Step several bridged environments at once from a single process.

SubprocVecEnv exists here because an in-process BOPTEST cannot be shared: one
FMU per process, so one environment per process.  A bridged environment has no
FMU in it, and its client spends the step blocked in socket.recv with the GIL
released, so plain threads overlap the test cases just as well and save a
process and a pipe each.

Only sound when a step spends its time blocked outside Python.  With local=True
the step runs pyfmi in this interpreter: use SubprocVecEnv there.

    from bridge import BridgeClient, ThreadVecEnv

    def make():
        return BoptestGymEnv(testcase='bestest_hydronic_heat_pump',
                             client=BridgeClient(testcase='bestest_hydronic_heat_pump'),
                             ...)

    venv = ThreadVecEnv([make] * 4)

One process saturates near 2000 control steps per second, being the cost of
assembling observations and rewards under one GIL; past that, put several of
these behind a SubprocVecEnv.

'''

from concurrent.futures import ThreadPoolExecutor

try:
    from stable_baselines3.common.vec_env import DummyVecEnv
except ImportError as exc:                        # pragma: no cover
    raise ImportError('ThreadVecEnv needs stable-baselines3; the bridge client '
                      'itself does not.') from exc


class ThreadVecEnv(DummyVecEnv):
    '''DummyVecEnv, but the environments step concurrently.

    Everything else -- spaces, resets, episode bookkeeping, the VecEnv contract
    -- is inherited unchanged, so this is a drop-in replacement wherever
    DummyVecEnv or SubprocVecEnv is used with bridged environments.

    Only sound when each environment's step spends its time blocked outside
    Python.  With local=True the step runs pyfmi in this interpreter, and
    two of them in one process corrupt each other: use SubprocVecEnv there.
    '''

    def __init__(self, env_fns):
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(env_fns)),
                                        thread_name_prefix='boptest-env')
        # Concurrently too: each one waits about a second for its FMU to load
        env_fns = list(env_fns)
        built = list(self._pool.map(lambda fn: fn(), env_fns))
        super().__init__([(lambda e=e: e) for e in built])

    def step_wait(self):
        def one(i):
            env = self.envs[i]
            obs, self.buf_rews[i], terminated, truncated, self.buf_infos[i] = \
                env.step(self.actions[i])
            self.buf_dones[i] = terminated or truncated
            # The VecEnv contract: a terminated episode reports its final
            # observation in info and hands back the reset one.
            self.buf_infos[i]['TimeLimit.truncated'] = truncated and not terminated
            if self.buf_dones[i]:
                self.buf_infos[i]['terminal_observation'] = obs
                obs, self.reset_infos[i] = env.reset()
            return i, obs

        for i, obs in self._pool.map(one, range(self.num_envs)):
            self._save_obs(i, obs)
        return (self._obs_from_buf(), self.buf_rews.copy(),
                self.buf_dones.copy(), list(self.buf_infos))

    def reset(self):
        def one(i):
            maybe_options = {'options': self._options[i]} if self._options[i] else {}
            obs, self.reset_infos[i] = self.envs[i].reset(seed=self._seeds[i],
                                                          **maybe_options)
            return i, obs
        for i, obs in self._pool.map(one, range(self.num_envs)):
            self._save_obs(i, obs)
        self._reset_seeds()
        self._reset_options()
        return self._obs_from_buf()

    def close(self):
        try:
            super().close()
        finally:
            self._pool.shutdown(wait=False)
