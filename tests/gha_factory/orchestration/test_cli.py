import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.gha_factory.orchestration import cli, engine


class FinalizerCLITests(unittest.TestCase):
    def controller_report(self, jobs, source_count=0, task_states=None):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / 'outputs'
            env = {
                'GITHUB_REPOSITORY': engine.REPO, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '101',
                'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_OUTPUT': str(output_path),
            }
            output = io.StringIO()
            states = task_states or {}
            def fake_control(*_args, **kwargs):
                telemetry = kwargs.get('telemetry')
                if telemetry is not None:
                    telemetry.update(queue_total=sum(states.values()), task_states=states)
                return jobs
            ctx = {'sources': [{'status': 'REVIEW_REQUIRED'}] * source_count}
            with patch.dict(os.environ, env), patch.object(cli.api, 'GitHub'), \
                    patch.object(cli.legacy, 'context', return_value=(ctx, 'a' * 64)), \
                    patch.object(engine, 'seed', return_value=[]), \
                    patch.object(engine, 'control', side_effect=fake_control), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(['controller']), 0)
            matrix = dict(line.split('=', 1) for line in output_path.read_text().splitlines())
            self.assertEqual(json.loads(matrix['jobs']), {'include': jobs})
            self.assertEqual(matrix['has_work'], str(bool(jobs)).lower())
            return json.loads(output.getvalue())

    def test_empty_queue_without_sources_reports_admission_block_not_productive_success(self):
        report = self.controller_report([])
        self.assertEqual(report['work_status'], 'BLOCKED_BY_SOURCE_ADMISSION')
        self.assertEqual(report['queue_status'], 'EMPTY_QUEUE')
        self.assertEqual(report['source_admission'], 'BLOCKED_BY_SOURCE_ADMISSION')
        self.assertEqual(report['task_states'], {})
        self.assertEqual(report['claimed'], 0)
        self.assertEqual(report['stage'], 'controller')
        self.assertFalse(report['production_publication'])

    def test_completed_history_is_not_mistaken_for_current_queue_work(self):
        report = self.controller_report([], task_states={'SUCCEEDED': 2})
        self.assertEqual(report['queue_status'], 'NO_ELIGIBLE_TASKS')
        self.assertEqual(report['task_states']['SUCCEEDED'], 2)
        self.assertEqual(report['work_status'], 'BLOCKED_BY_SOURCE_ADMISSION')

    def test_unapproved_recorded_source_does_not_claim_productive_success(self):
        report = self.controller_report([], source_count=1, task_states={'BLOCKED_SOURCE': 1})
        self.assertEqual(report['work_status'], 'SUCCESS_NO_WORK')
        self.assertEqual(report['queue_status'], 'NO_ELIGIBLE_TASKS')
        self.assertEqual(report['source_admission'], 'ADMISSION_CHECK_REQUIRED')
        self.assertFalse(report['production_publication'])

    def test_claimed_tasks_are_not_productive_success_before_worker_results(self):
        report = self.controller_report([{'number': 7, 'task_id': 'a' * 64}])
        self.assertEqual(report['work_status'], 'WORK_CLAIMED')
        self.assertEqual(report['claimed'], 1)
        self.assertEqual(report['stage'], 'controller')
        self.assertFalse(report['production_publication'])

    def test_partial_completion_is_reported_with_nonzero_exit(self):
        result = {'issue': 2, 'state': 'SUCCEEDED'}
        error = {'issue': 1, 'error': 'FINALIZATION_REJECTED'}
        env = {
            'GITHUB_REPOSITORY': engine.REPO, 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_RUN_ID': '101',
            'GITHUB_RUN_ATTEMPT': '1', 'JOBS_JSON': '{"include":[]}',
        }
        output = io.StringIO()
        with patch.dict(os.environ, env), patch.object(cli.api, 'GitHub'), \
                patch.object(engine, 'finalize', side_effect=engine.FinalizationError([result], [error])), \
                contextlib.redirect_stdout(output):
            code = cli.main(['finalize', '--artifacts', '/tmp/unused-test-artifacts'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {'results': [result], 'errors': [error]})

    def test_existing_workflow_validates_its_dispatcher_dependencies(self):
        # Contract guard: edits to imported dispatcher/admission code must run
        # the existing integration job, rather than silently bypass it.
        workflow = Path('.github/workflows/gha_dispatcher.yml').read_text()
        paths = workflow.split('  pull_request:', 1)[1].split('  schedule:', 1)[0]
        for folder in ('orchestration', 'dispatcher', 'admission'):
            self.assertIn('tools/gha_factory/' + folder + '/**', paths)
            self.assertIn('tests/gha_factory/' + folder + '/**', paths)
