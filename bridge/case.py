'''One BOPTEST test case, answering the calls BoptestClient makes.

The only part of the bridge that touches BOPTEST, and so the only part that
needs pyfmi.  It offers the same get/put/post/kpis surface as BoptestClient,
which is why the client can forward a call without translating it.

One test case per process: every BOPTEST test case FMU declares
canBeInstantiatedOnlyOncePerProcess=true and a second one corrupts both.

'''

import inspect
import os
import shutil
import sys
import tempfile

READ = {'name': 'get_name', 'measurements': 'get_measurements',
        'inputs': 'get_inputs', 'forecast_points': 'get_forecast_points',
        'step': 'get_step', 'scenario': 'get_scenario', 'version': 'get_version'}


class TestCaseRunner(object):

    def __init__(self, boptest_root, testcase, testcase_dir=None, options=None):
        for path in (boptest_root, os.path.join(boptest_root, 'kpis'),
                     os.path.join(boptest_root, 'forecast'),
                     os.path.join(boptest_root, 'data')):
            if path not in sys.path:
                sys.path.insert(0, path)

        testcase_dir = testcase_dir or os.path.join(boptest_root, 'testcases')
        fmupath = os.path.join(testcase_dir, testcase, 'models', 'wrapped.fmu')
        if not os.path.isfile(fmupath):
            raise IOError('No test case FMU at {0}. BOPTEST distributes these '
                          'separately from the source tree.'.format(fmupath))

        self.workdir = tempfile.mkdtemp(prefix='boptest_{0}_'.format(testcase))
        shutil.copyfile(os.path.join(boptest_root, 'version.txt'),
                        os.path.join(self.workdir, 'version.txt'))
        # This process exists only to run this test case, so it takes the
        # working directory: pyfmi writes its log and result files relative to
        # the cwd, and an in-process backend cannot move the cwd without moving
        # the caller's too.
        os.chdir(self.workdir)

        from testcase import TestCase
        forecast_params = os.path.join(boptest_root, 'forecast',
                                       'forecast_uncertainty_params.json')
        try:
            self.case = TestCase(fmupath, forecast_params, **(options or {}))
        except TypeError:
            # A BOPTEST without these options: correct, just slower
            self.case = TestCase(fmupath, forecast_params)
        self.case.options['result_file_name'] = os.path.join(self.workdir,
                                                             'result.mat')
        self._warmup_interval = 'warmup_interval' in \
            inspect.signature(self.case.initialize).parameters
        self._kpi_names = bool(inspect.signature(self.case.get_kpis).parameters)

    def call(self, method, endpoint, payload):
        '''Answer one client call, returning BOPTEST's (status, message, payload).'''

        case = self.case
        payload = payload or {}
        if method == 'get':
            if endpoint == 'kpi':
                names = payload.get('names')
                if names and self._kpi_names:
                    return case.get_kpis(names)
                return case.get_kpis()
            if endpoint in READ:
                return getattr(case, READ[endpoint])()
        elif method == 'put':
            if endpoint == 'initialize':
                kwargs = {}
                if payload.get('warmup_interval') is not None and self._warmup_interval:
                    kwargs['warmup_interval'] = payload['warmup_interval']
                return case.initialize(payload['start_time'],
                                       payload['warmup_period'], **kwargs)
            if endpoint == 'step':
                return case.set_step(payload['step'])
            if endpoint == 'scenario':
                scenario = dict(payload)
                for key in ('electricity_price', 'time_period',
                            'temperature_uncertainty', 'solar_uncertainty', 'seed'):
                    scenario.setdefault(key, None)
                return case.set_scenario(scenario)
            if endpoint == 'results':
                return case.get_results(payload['point_names'],
                                        payload['start_time'], payload['final_time'])
            if endpoint == 'forecast':
                return case.get_forecast(payload['point_names'],
                                         payload['horizon'], payload['interval'])
        elif method == 'post' and endpoint == 'advance':
            return case.advance(payload)
        raise ValueError('Unsupported {0} "{1}"'.format(method.upper(), endpoint))

    def batch(self, calls):
        '''Answer several calls, so that one control step is one round trip.'''

        out = []
        for method, endpoint, payload in calls:
            try:
                out.append(list(self.call(method, endpoint, payload)))
            except Exception as exc:
                out.append([500, '{0}: {1}'.format(type(exc).__name__, exc), None])
        return out

    def close(self):
        try:
            os.chdir('/')
        except OSError:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)
