import unittest
import os
from engine import ChangeImpactEngine

class TestMixedTrees(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.engine = ChangeImpactEngine(self.repo_root)

        self.test_files = [
            'test_py_a.py',
            'test_py_b.py',
            'test_dart_a.dart',
            'test_dart_b.dart'
        ]

    def tearDown(self):
        for f in self.test_files:
            path = os.path.join(self.repo_root, f)
            if os.path.exists(path):
                os.remove(path)

    def write_file(self, filename, content):
        with open(os.path.join(self.repo_root, filename), 'w') as f:
            f.write(content)

    def test_mixed_changes(self):
        self.write_file('test_py_a.py', "import test_py_b\n")
        self.write_file('test_py_b.py', "def func(): pass\n")
        self.write_file('test_dart_a.dart', "import 'test_dart_b.dart';\n")
        self.write_file('test_dart_b.dart', "void func() {}\n")

        result = self.engine.analyze_impact(['test_py_b.py', 'test_dart_b.dart'])

        self.assertIn('test_py_a.py', result['impacted_files'])
        self.assertIn('test_py_b.py', result['impacted_files'])
        self.assertIn('test_dart_a.dart', result['impacted_files'])
        self.assertIn('test_dart_b.dart', result['impacted_files'])

if __name__ == '__main__':
    unittest.main()
