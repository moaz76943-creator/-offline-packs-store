import unittest
import os
from engine import ChangeImpactEngine

class TestRenames(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.engine = ChangeImpactEngine(self.repo_root)

        self.test_files = [
            'test_user_of_old.py'
        ]

    def tearDown(self):
        for f in self.test_files:
            path = os.path.join(self.repo_root, f)
            if os.path.exists(path):
                os.remove(path)

    def write_file(self, filename, content):
        with open(os.path.join(self.repo_root, filename), 'w') as f:
            f.write(content)

    def test_renames(self):
        # We test that a file that no longer exists in the filesystem (renamed/deleted)
        # can still be processed as an input, even if the graph doesn't have it directly.
        # The engine should still find its dependents if they mention its old name.
        self.write_file('test_user_of_old.py', "import test_old_name\n")

        result = self.engine.analyze_impact(['test_old_name.py'])

        self.assertIn('test_old_name.py', result['impacted_files'])
        self.assertIn('test_user_of_old.py', result['impacted_files'])

if __name__ == '__main__':
    unittest.main()
