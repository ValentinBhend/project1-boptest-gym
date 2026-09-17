'''One BOPTEST test case, driven by named operations.

The only part of the bridge that touches BOPTEST, and so the only part that
needs pyfmi.  It knows nothing about how it is reached.

One test case per process: every BOPTEST test case FMU declares
canBeInstantiatedOnlyOncePerProcess=true and a second one corrupts both.

'''

import inspect
import os
import shutil
import sys
import tempfile


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

    def call(self, op, args):
        case = self.case
        args = args or {}
        if op == 'advance':
            return case.advance(args)
        if op == 'initialize':
            kwargs = {}
            if args.get('warmup_interval') is not None and self._warmup_interval:
                kwargs['warmup_interval'] = args['warmup_interval']
            return case.initialize(args['start_time'], args['warmup_period'],
                                   **kwargs)
        if op == 'kpi':
            names = args.get('names')
            if names and self._kpi_names:
                return case.get_kpis(names)
            return case.get_kpis()
        if op == 'forecast':
            return case.get_forecast(args['point_names'], args['horizon'],
                                     args['interval'])
        if op == 'results':
            return case.get_results(args['point_names'], args['start_time'],
                                    args['final_time'])
        if op == 'step':
            return case.set_step(args['step'])
        if op == 'scenario':
            scenario = dict(args)
            for key in ('electricity_price', 'time_period',
                        'temperature_uncertainty', 'solar_uncertainty', 'seed'):
                scenario.setdefault(key, None)
            return case.set_scenario(scenario)
        handlers = {'name': case.get_name,
                    'measurements': case.get_measurements,
                    'inputs': case.get_inputs,
                    'forecast_points': case.get_forecast_points,
                    'get_step': case.get_step,
                    'get_scenario': case.get_scenario,
                    'version': case.get_version}
        if op not in handlers:
            raise ValueError('Unsupported operation "{0}"'.format(op))
        return handlers[op]()

    def batch(self, ops):
        '''Run several operations and return a result for each.

        Batching is what keeps a control step to one round trip, since the
        environment asks for the state, the reward KPIs and the forecast
        separately.

        '''

        out = []
        for op, args in ops:
            try:
                status, message, payload = self.call(op, args)
                out.append([status, message, payload])
            except Exception as exc:
                out.append([500, '{0}: {1}'.format(type(exc).__name__, exc), None])
        return out

    def close(self):
        try:
            os.chdir('/')
        except OSError:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)
