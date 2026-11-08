import unittest
import os
import shutil
from engine import ChangeImpactEngine

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.engine = ChangeImpactEngine(self.repo_root)

        self.test_files = [
            'test_py_a.py',
            'test_py_b.py',
            'test_py_c.py',
            '__init__.py',
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

    def test_python_cyclic_imports(self):
        self.write_file('test_py_a.py', "import test_py_b\n")
        self.write_file('test_py_b.py', "import test_py_a\n")

        result = self.engine.analyze_impact(['test_py_a.py'])
        self.assertIn('test_py_a.py', result['impacted_files'])
        self.assertIn('test_py_b.py', result['impacted_files'])

    def test_dynamic_uncertainty(self):
        self.write_file('test_py_c.py', "module = __import__('os')\n")

        result = self.engine.analyze_impact(['test_py_c.py'])
        self.assertIn('test_py_c.py', result['uncertain_files'])
        self.assertIn('ALL_TESTS', result['impacted_tests'])

    def test_dart_blocked(self):
        parser_bin = os.path.join(self.repo_root, 'tools', 'change_impact', 'dart_ast_parser', 'bin', 'parse.dart')
        if os.path.exists(parser_bin):
            os.rename(parser_bin, parser_bin + '.bak')

        self.write_file('test_dart_a.dart', "import 'dart:io';\n")
        result = self.engine.analyze_impact(['test_dart_a.dart'])

        self.assertEqual(result['error'], 'BLOCKED: Dart parser not available')

        if os.path.exists(parser_bin + '.bak'):
            os.rename(parser_bin + '.bak', parser_bin)

    def test_python_syntax_error(self):
        self.write_file('test_py_a.py', "def invalid_syntax(\n")
        result = self.engine.parse_python_ast('test_py_a.py')
        self.assertTrue(result['error'].startswith('SyntaxError'))

    def test_dart_indirect_imports(self):
        self.write_file('test_dart_a.dart', "import 'test_dart_b.dart';\n")
        self.write_file('test_dart_b.dart', "void func() {}\n")

        result = self.engine.analyze_impact(['test_dart_b.dart'])
        self.assertIn('test_dart_a.dart', result['impacted_files'])
        self.assertIn('test_dart_b.dart', result['impacted_files'])

    def test_python_init_import(self):
        self.write_file('__init__.py', "from . import test_py_a\n")
        self.write_file('test_py_a.py', "def func(): pass\n")

        result = self.engine.analyze_impact(['test_py_a.py'])
        self.assertIn('__init__.py', result['impacted_files'])

    def test_dart_package_import(self):
        self.write_file('test_dart_a.dart', "import 'package:my_repo/test_dart_b.dart';\n")
        self.write_file('test_dart_b.dart', "void func() {}\n")

        result = self.engine.analyze_impact(['test_dart_b.dart'])
        self.assertIn('test_dart_a.dart', result['impacted_files'])

if __name__ == '__main__':
    unittest.main()
