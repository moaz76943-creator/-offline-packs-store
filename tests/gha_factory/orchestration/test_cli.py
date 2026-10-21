import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.gha_factory.orchestration import cli, engine


class FinalizerCLITests(unittest.TestCase):
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
