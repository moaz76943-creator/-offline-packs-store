import unittest
import subprocess
import os
import json

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.cli_path = os.path.join(self.repo_root, 'tools', 'change_impact', 'cli.py')

    def test_cli_basic(self):
        result = subprocess.run(
            ['python3', self.cli_path, 'setup_repo.py', '--repo-root', self.repo_root],
            capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
        self.assertIn('setup_repo.py', data['impacted_files'])
        self.assertIn('impacted_tests', data)
        self.assertIn('uncertain_files', data)

if __name__ == '__main__':
    unittest.main()
