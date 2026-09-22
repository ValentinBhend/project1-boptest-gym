# BOPTEST-Gym

BOPTESTS-Gym is the [Gymnasium](https://gymnasium.farama.org/index.html) environment of the [BOPTEST](https://github.com/ibpsa/project1-boptest) framework. This repository accommodates the BOPTEST API to the Gymnasium standard in order to facilitate the implementation, assessment and benchmarking of reinforcement learning (RL) algorithms for their application in building energy management. RL algorithms from the [Stable-Baselines 3](https://github.com/DLR-RM/stable-baselines3) repository are used to exemplify and test this framework. 

The environment is described in [this paper](https://www.researchgate.net/publication/354386346_An_OpenAI-Gym_environment_for_the_Building_Optimization_Testing_BOPTEST_framework). 

## Structure
- `boptestGymEnv.py` contains the core functionality of this Gymnasium environment.
- `environment.yml` contains the dependencies required to run this software. 
- `/examples` contains prototype code for the interaction of RL algorithms with an emulator building model from BOPTEST. 
- `/testing` contains code for testing this software. 

## Quick-Start

1) Create an environment from the `environment.yml` file provided (instructions [here](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-from-an-environment-yml-file)). You can also see our Dockerfile in [testing/Dockerfile](testing/Dockerfile) that we use to define our testing environment. 
2) Run the example below that uses the [Bestest hydronic case with a heat-pump](https://github.com/ibpsa/project1-boptest/tree/master/testcases/bestest_hydronic_heat_pump) and the [DQN algorithm](https://stable-baselines3.readthedocs.io/en/master/modules/dqn.html) from Stable-Baselines: 

```python
from boptestGymEnv import BoptestGymEnv, NormalizedObservationWrapper, DiscretizedActionWrapper
from stable_baselines3 import DQN

# url for the BOPTEST service. 
url = 'https://api.boptest.net' 

# Decide the state-action space of your test case
env = BoptestGymEnv(
        url                  = url,
        testcase             = 'bestest_hydronic_heat_pump',
        actions              = ['oveHeaPumY_u'],
        observations         = {'time':(0,604800),
                                'reaTZon_y':(280.,310.),
                                'TDryBul':(265,303),
                                'HDirNor':(0,862),
                                'InternalGainsRad[1]':(0,219),
                                'PriceElectricPowerHighlyDynamic':(-0.4,0.4),
                                'LowerSetp[1]':(280.,310.),
                                'UpperSetp[1]':(280.,310.)}, 
        predictive_period    = 24*3600, 
        regressive_period    = 6*3600, 
        random_start_time    = True,
        max_episode_length   = 24*3600,
        warmup_period        = 24*3600,
        step_period          = 3600)

# Normalize observations and discretize action space
env = NormalizedObservationWrapper(env)
env = DiscretizedActionWrapper(env,n_bins_act=10)

# Instantiate an RL agent
model = DQN('MlpPolicy', env, verbose=1, gamma=0.99,
            learning_rate=5e-4, batch_size=24, 
            buffer_size=365*24, learning_starts=24, train_freq=1)

# Main training loop
model.learn(total_timesteps=10)

# Loop for one episode of experience (one day)
done = False
obs, _ = env.reset()
while not done:
  action, _ = model.predict(obs, deterministic=True) 
  obs,reward,terminated,truncated,info = env.step(action)
  done = (terminated or truncated)

# Obtain KPIs for evaluation
env.get_kpis()

```

In [this tutorial](https://github.com/ibpsa/project1-boptest-gym/blob/master/docs/tutorials/CCAI_Summer_School_2022/Building_Control_with_RL_using_BOPTEST.ipynb) you can find more details on how to use BOPTEST-Gym and on RL applied to buildings in general. 

### Note 1: on running BOPTEST in the server vs. locally
The previous example interacts with BOPTEST in a server at `https://api.boptest.net` which is readily available anytime. Interacting with BOPTEST from this server requires less configuration effort but is slower because of the communication overhead between the agent and the test case running in the cloud. Use this approach when you want to quickly check out the functionality of this repository. 

If you prioritize speed (which is usually the case when training RL agents), running BOPTEST locally is substantially faster. 
You can do so by downloading the BOPTEST repository and running:
```bash
docker compose up web worker provision

```

Further details in the [BOPTEST GitHub page](https://github.com/ibpsa/project1-boptest/blob/master/README.md#quick-start-to-deploy-and-use-boptest-on-a-local-computer). 

Then you only need to change the `url` to point to your local BOPTEST service deployment instead of the remote server (`url = 'http://127.0.0.1').

### Note 2: on running BOPTEST locally in a vectorized environment

BOPTEST allows the deployment of multiple test case instances using Docker Compose. 
Running a vectorized environment enables the deployment of as many BoptestGymEnv instances as cores you have available for the agent to learn from all of them in parallel. See [here](https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html) for more information, we specifically use [`SubprocVecEnv`](https://stable-baselines3.readthedocs.io/en/master/guide/vec_envs.html#subprocvecenv). This can substantially speed up the training process. 

To do so, deploy BOPTEST with multiple workers to spin multiple test cases. See the example below that prepares BOPTEST to spin two test cases.

```bash
docker compose up --scale worker=2 web worker provision
```

Then you can train an RL agent with parallel learning with the vectorized BOPTEST-gym environment. See [`/examples/run_vectorized.py`](https://github.com/ibpsa/project1-boptest-gym/blob/master/examples/run_vectorized.py) for an example on how to do so. 

### Note 3: on reducing the overhead per step

- `direct_step=True` asks BOPTEST to step the emulator FMU with `do_step` directly instead of building a simulation algorithm and result handler for every control step. Measurements and KPIs are unchanged. It is sent when the test case is selected, so a BOPTEST that does not support it simply ignores it.

- `fmu_log_level=0` and `log_level='WARNING'` turn BOPTEST's logging down. Both are unset by default, leaving BOPTEST its own levels. On their own they change nothing measurable, because pyfmi's per-step overhead hides the logging cost; combined with `direct_step` they are worth a further 1.16x.

- `warmup_interval=<seconds>`, or `'inf'` for a single step over the whole warmup period, sets the grid the warmup simulation runs on and roughly halves the cost of an episode reset. Control steps always use 30 s. Coarsening it moves the state reached at the start time only within the FMU solver's own error tolerance: with a one-day warmup on `bestest_hydronic_heat_pump`, every grid from 60 s up to a single step shifts the zone temperature by less than 1e-05 K and the reported KPIs by less than 1e-05 relative, and not monotonically in the grid, which is solver noise rather than discretisation error. Left unset it is not sent at all, so BOPTEST keeps its own 30 s grid and results are bit-identical. A BOPTEST that does not support it ignores it.

Independently of those, the reward now asks BOPTEST only for the KPIs it reads (`cost_tot` and `tdis_tot`, listed in `REWARD_KPIS`) rather than for all of them. The peak demand KPIs are maxima over the whole test period and so get more expensive the longer an episode runs, while these two do not. A BOPTEST that does not support requesting a subset returns the full set, which is still correct, so this needs no configuration and never fails.

### Note 4: on running the test case in its own process

A control step over the REST API carries three HTTP requests through the web tier, a message broker and a worker. `bridge` runs the test case in a process of its own and talks to it over one socket, which on `bestest_hydronic_heat_pump` at a 900 s step costs 9.7 ms against 18.1 ms, measured alternately in one session with the options in Note 3 already applied to both.

Start it with the image your BOPTEST checkout already builds, and nothing else — no web tier, no broker, no object store:

```bash
BOPTEST_SRC=/path/to/project1-boptest docker compose -f bridge/compose.yml up
```

Then pass a client, and the rest of the environment is unchanged:

```python
from bridge import BridgeClient

env = BoptestGymEnv(testcase='bestest_hydronic_heat_pump',
                    client=BridgeClient(testcase='bestest_hydronic_heat_pump',
                                        select_options={'direct_step': True}),
                    ...)
```

The agent's environment needs none of BOPTEST's: `BridgeClient` imports only the standard library, so pyfmi, the numpy BOPTEST pins and `libgfortran.so.4` all stay in the container. Each environment gets its own process and its own FMU, so `canBeInstantiatedOnlyOncePerProcess` is satisfied however many you run, a test case that hangs in the solver can be killed, and closing the connection ends it, so an agent that crashes leaves nothing behind.

For several environments use `SubprocVecEnv` as in Note 2; each environment gets its own worker.

`BOPTEST_SRC` is the checkout you deploy BOPTEST from, which is where the test case FMUs live. `BOPTEST_BRIDGE_PORT` moves the port from its default of 5000, and `BOPTEST_BRIDGE_URL` tells the client where to find it.
### Note 5: the whole thing from an empty directory

Notes 1 to 4 each describe one option. This is all of them in order, local
rather than the public server, with every option in Notes 3 and 4 applied and
parallel training at the end. The project is the clone itself, which already
carries a `pyproject.toml`.

#### Project setup:

```bash
# 1. the two repositories: the gym, and BOPTEST for its test case FMUs.
#    Both on integration -- master has none of the options in Note 3.
git clone -b integration https://github.com/ValentinBhend/project1-boptest-gym
git clone -b integration https://github.com/ValentinBhend/project1-boptest

# 2. the worker image.  Once ever, not once per session: images survive a
#    reboot, and you already have this one if you deployed BOPTEST as in Note 1.
cd project1-boptest && docker compose build worker && cd ..

# 3. the agent environment; none of BOPTEST's runtime belongs in it
cd project1-boptest-gym
uv python pin 3.10
uv add "stable-baselines3==2.0.0" "gymnasium==0.28.1" "numpy==1.25.0" \
       "pandas==2.0.3" "matplotlib==3.7.1" "scipy==1.11.1" \
       --extra-index-url https://download.pytorch.org/whl/cpu
```

#### Running the train example:

```bash
# 4. the test cases, one process each: no web tier, no broker, no object store
export BOPTEST_SRC=../../project1-boptest    # relative to bridge/, not to you
docker compose -f bridge/compose.yml up -d

# 5. train, and see where the throughput goes
uv run train.py
#   16 environments, aggregate
#     no sb3, constant actions      456 steps/s    28.5 per env    4.7 sim days/wall s
#     no sb3, random actions        244 steps/s    15.3 per env    2.5 sim days/wall s
#     sb3 SAC, warmup               222 steps/s    13.9 per env    2.3 sim days/wall s
#     sb3 SAC, learning             176 steps/s    11.0 per env    1.8 sim days/wall s
```

Reading down that list: **constant actions are worth about 1.9x on their own**,
because the solver coasts when the input never changes, so any benchmark using
them is optimistic by that much. Stable-Baselines' rollout machinery costs a
further 9%, and SAC's gradient updates 21% on top of that -- only that last step
is about the learner rather than the building. Sixteen environments was the best
count on a 7-core laptop.

The four run in order on a warming machine, and this one loses roughly a third
of its throughput over three back-to-back runs, so the later arms are the
pessimistic ones and the ratios travel better than the absolute numbers.

`train.py`:

```python
"""Parallel training against the bridge, and where the throughput goes.

Four ways of driving the same 16 environments, one after another.  Delete the
first three and what is left is an ordinary training script.
"""

import time

import numpy as np
from boptestGymEnv import (BoptestGymEnv, NormalizedActionWrapper,
                           NormalizedObservationWrapper)
from bridge import BridgeClient
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import SubprocVecEnv

CASE = 'bestest_hydronic_heat_pump'
N_ENVS = 16                                     # 16 was fastest on 7 cores
STEPS = 3200                                    # env steps per measurement
SELECT = {'direct_step': True, 'fmu_log_level': 0, 'log_level': 'WARNING'}


def make():
    env = BoptestGymEnv(
        testcase=CASE,
        client=BridgeClient(testcase=CASE, select_options=SELECT),
        actions=['oveHeaPumY_u'],
        observations={'time': (0, 604800), 'reaTZon_y': (280., 310.)},
        max_episode_length=24*3600, warmup_period=24*3600, step_period=900,
        start_time=31*24*3600,
        warmup_interval='inf',
    )
    return NormalizedActionWrapper(NormalizedObservationWrapper(env))


if __name__ == '__main__':          # SubprocVecEnv starts its workers by import
    venv = SubprocVecEnv([make] * N_ENVS)
    results = []

    # 1. no sb3, constant actions.  The solver coasts when the input never
    #    changes, so this is the optimistic bound rather than a real rate.
    venv.reset()
    action = np.full((N_ENVS,) + venv.action_space.shape, 0.5, dtype=np.float32)
    for _ in range(3):
        venv.step(action)
    start = time.perf_counter()
    for _ in range(STEPS // N_ENVS):
        venv.step(action)
    constant_sps = STEPS / (time.perf_counter() - start)
    results.append(('no sb3, constant actions', constant_sps))

    # 2. no sb3, random actions.  What the transport and the solver really carry.
    venv.reset()
    for _ in range(3):
        venv.step(np.array([venv.action_space.sample() for _ in range(N_ENVS)]))
    start = time.perf_counter()
    for _ in range(STEPS // N_ENVS):
        venv.step(np.array([venv.action_space.sample() for _ in range(N_ENVS)]))
    random_sps = STEPS / (time.perf_counter() - start)
    results.append(('no sb3, random actions', random_sps))

    # 3. sb3 SAC collecting rollouts.  learning_starts above STEPS means no
    #    gradient update ever runs, so this is the cost sb3 itself adds.
    model = SAC('MlpPolicy', venv, verbose=1, learning_starts=10**9)
    start = time.perf_counter()
    model.learn(total_timesteps=STEPS)
    warmup_sps = STEPS / (time.perf_counter() - start)
    results.append(('sb3 SAC, warmup', warmup_sps))

    # 4. sb3 SAC, ordinary training.
    model = SAC('MlpPolicy', venv, verbose=1)
    start = time.perf_counter()
    model.learn(total_timesteps=STEPS)
    learning_sps = STEPS / (time.perf_counter() - start)
    results.append(('sb3 SAC, learning', learning_sps))

    venv.close()

    print('\n%d environments, aggregate' % N_ENVS)
    for name, sps in results:
        print('  %-26s %6.0f steps/s   %5.1f per env   %4.1f sim days/wall s'
              % (name, sps, sps / N_ENVS, sps * 900 / 86400))
```

Things that are easy to get wrong here:

- **`select_options` goes on the client, not on `BoptestGymEnv`.** Supplying a
  `client` means the environment no longer selects the test case, so its own
  `direct_step` and `log_level` arguments are never sent. Forgetting them costs
  the whole of Note 3 and says nothing.
- **BOPTEST has to be on `integration` too.** Note 3's options are answered by
  BOPTEST, not by the gym, and one that does not know them ignores them rather
  than failing -- which is deliberate, and means a `master` checkout runs
  quietly at less than half speed. Measured on one machine, same FMU, same
  image, only the checkout differing: 77 against 167 steps/s over four
  environments. `grep -c direct_step testcase.py` in the checkout is 0 on
  `master` and non-zero on `integration`.
- **SAC needs a continuous action space,** so this wraps with
  `NormalizedActionWrapper`. `DiscretizedActionWrapper` is for DQN and SAC will
  refuse it.
- **`learning_starts` above the measured window** is what makes the warmup arm
  a warmup. Left at its default of 100, SAC runs gradient updates throughout and
  the arm measures the same thing as the one below it.
- **`BOPTEST_SRC` is relative to `bridge/`, not to you.** Paths in a compose
  file resolve against the directory that file is in, which is why `../..`
  above is the sibling of this checkout -- the same reason `..:/boptestgym`
  inside the file means the repository root. Get it wrong and Docker creates
  an empty directory and mounts that: the bridge starts, reports
  `BRIDGE READY`, and every select fails with `No test case FMU`. Do not
  reach for `--project-directory .` to make it relative to your shell -- it
  fixes this path and breaks the other one, and the server then exits with
  `No module named 'bridge'`. An absolute path works too. The variable has to
  be set for every later `docker compose -f bridge/compose.yml` command,
  including `ps`, `logs` and `down`.
- **The `__main__` guard is not optional.** `SubprocVecEnv` starts its workers
  by importing the script, and without the guard that import starts them again.
- **No `--scale`.** Note 2 needs `--scale worker=n` because each celery worker
  holds one test case. The bridge forks per connection, so one container serves
  every environment you open against it, and closing a connection ends its
  worker.
- **Only steps 4 and 5 repeat.** `docker compose -f bridge/compose.yml up -d`
  after a reboot, because containers stop and images do not.
- **There is no `uv init` step.** The clone is already a uv project, so `uv
  init` refuses; `uv python pin` sets the interpreter that `pyproject.toml`
  alone does not. `uv add` then edits that file and writes `uv.lock` and
  `.python-version`, so expect the checkout to go dirty.

Conda instead of uv, if you prefer the environment in the Quick-Start:
`conda env create -f environment.yml && conda activate boptestgym` pins the
same versions -- the `uv add` above is that file's pip section with the CUDA
wheels left out, which is the only difference.

## Versioning and main dependencies

Current BOPTEST-Gym version is `v0.8.0` which is compatible with BOPTEST `v0.8.0` 
(BOPTEST-Gym version should always be even with the BOPTEST version used). 
The framework has been tested with `gymnasium==0.28.1` and `stable-baselines3==2.0.0`.
You can see [testing/Dockerfile](testing/Dockerfile) for a full description of the testing environment. 

## Citing the project

Please use the following reference if you used this repository for your research.

```
@inproceedings{boptestgym2021,
	author = {Javier Arroyo and Carlo Manna and Fred Spiessens and Lieve Helsen},
	title = {{An OpenAI-Gym environment for the Building Optimization Testing (BOPTEST) framework}},
	year = {2021},
	month = {September},
	booktitle = {Proceedings of the 17th IBPSA Conference},
	address = {Bruges, Belgium},
}

```
