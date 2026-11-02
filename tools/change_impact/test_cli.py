import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

class TestChangeImpactCLI(unittest.TestCase):
    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def test_cli_basic(self):
        f1 = Path(self.repo_root) / 'a.py'
        f2 = Path(self.repo_root) / 'b.py'

        f1.write_text("import b")
        f2.write_text("def b_func(): pass")

        # We need to run the CLI
        cli_path = Path(os.getcwd()) / 'tools' / 'change_impact' / 'cli.py'

        result = subprocess.run(
            ['python3', str(cli_path), '--repo-root', self.repo_root, '--changed-files', 'b.py'],
            capture_output=True,
            text=True
        )

        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIn('a.py', output['impacted_files'])
        self.assertIn('b.py', output['impacted_files'])
        self.assertFalse(output['uncertain'])

if __name__ == '__main__':
    unittest.main()
