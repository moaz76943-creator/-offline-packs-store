import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.change_impact.engine import DependencyEngine

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

        # mock parser path for engine
        self.dart_parser_dir = self.repo_root / 'tools' / 'change_impact' / 'dart_parser'
        self.dart_parser_dir.mkdir(parents=True)
        self.dart_parser_path = self.dart_parser_dir / 'parser.dart'

        # Copy actual dart parser to temp dir so it works
        actual_parser = Path.cwd() / 'tools' / 'change_impact' / 'dart_parser' / 'parser.dart'
        if actual_parser.exists():
            with open(actual_parser, 'r') as f:
                content = f.read()
            with open(self.dart_parser_path, 'w') as f:
                f.write(content)

        actual_pubspec = Path.cwd() / 'tools' / 'change_impact' / 'dart_parser' / 'pubspec.yaml'
        if actual_pubspec.exists():
            with open(actual_pubspec, 'r') as f:
                content = f.read()
            with open(self.dart_parser_dir / 'pubspec.yaml', 'w') as f:
                f.write(content)

            # Need to run pub get in the temp dir
            subprocess.run(['dart', 'pub', 'get'], cwd=self.dart_parser_dir, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_file(self, rel_path, content):
        p = self.repo_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w') as f:
            f.write(content)
        return str(p)

    def test_python_simple_impact(self):
        self.write_file('a.py', "def foo(): pass")
        self.write_file('b.py', "import a\ndef bar(): a.foo()")
        self.write_file('test_b.py', "import b\ndef test_bar(): b.bar()")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path
        engine.build_graph()

        files, tests = engine.get_impact(['a.py'])
        self.assertIn('a.py', files)
        self.assertIn('b.py', files)
        self.assertIn('test_b.py', files)
        self.assertIn('test_b.py', tests)

    def test_python_cyclic(self):
        self.write_file('a.py', "import b\ndef foo(): pass")
        self.write_file('b.py', "import a\ndef bar(): pass")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path
        engine.build_graph()

        files, tests = engine.get_impact(['a.py'])
        self.assertIn('a.py', files)
        self.assertIn('b.py', files)

        files, tests = engine.get_impact(['b.py'])
        self.assertIn('a.py', files)
        self.assertIn('b.py', files)

    def test_python_dynamic_uncertainty(self):
        self.write_file('a.py', "def foo(): pass")
        self.write_file('b.py', "import a")
        self.write_file('c.py', "def load(): return __import__('unknown')")
        self.write_file('test_c.py', "import c")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path
        engine.build_graph()

        files, tests = engine.get_impact(['a.py'])
        self.assertIn('a.py', files)
        self.assertIn('b.py', files)
        # Because of dynamic uncertainty, c and test_c are included
        self.assertIn('c.py', files)
        self.assertIn('test_c.py', files)
        self.assertIn('test_c.py', tests)

    def test_dart_simple_impact(self):
        self.write_file('lib/a.dart', "void foo() {}")
        self.write_file('lib/b.dart', "import 'a.dart'; void bar() {}")
        self.write_file('test_b_test.dart', "import 'lib/b.dart'; void main() {}")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path
        engine.build_graph()

        files, tests = engine.get_impact(['lib/a.dart'])
        self.assertIn('lib/a.dart', files)
        self.assertIn('lib/b.dart', files)
        self.assertIn('test_b_test.dart', files)
        self.assertIn('test_b_test.dart', tests)

    def test_mixed_environment(self):
        self.write_file('a.py', "def foo(): pass")
        self.write_file('b.py', "import a")
        self.write_file('lib/c.dart', "void foo() {}")
        self.write_file('lib/d.dart', "import 'c.dart'; void bar() {}")
        self.write_file('test_d_test.dart', "import 'lib/d.dart'; void main() {}")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path
        engine.build_graph()

        # Changing py shouldn't affect dart if there's no dynamic link
        files, tests = engine.get_impact(['a.py'])
        self.assertIn('b.py', files)
        self.assertNotIn('lib/d.dart', files)

        # Changing dart shouldn't affect py
        files, tests = engine.get_impact(['lib/c.dart'])
        self.assertIn('lib/d.dart', files)
        self.assertNotIn('b.py', files)

    def test_missing_parser_capability(self):
        # Point parser path to non-existent file
        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.repo_root / 'non_existent.dart'
        self.write_file('lib/a.dart', "void foo() {}")

        with self.assertRaises(SystemExit) as cm:
            engine.build_graph()
        self.assertEqual(cm.exception.code, 1)

    def test_syntax_error(self):
        self.write_file('error.py', "def foo( ^")
        self.write_file('lib/error.dart', "void foo( ^")

        engine = DependencyEngine(str(self.repo_root))
        engine.dart_parser_path = self.dart_parser_path

        # Should not crash, just empty deps
        engine.build_graph()

        files, _ = engine.get_impact(['error.py'])
        self.assertEqual(files, ['error.py'])

        files, _ = engine.get_impact(['lib/error.dart'])
        self.assertEqual(files, ['lib/error.dart'])

if __name__ == '__main__':
    unittest.main()
