import unittest
import tempfile
import os
import shutil
import json
from unittest.mock import patch
from pathlib import Path
from tools.change_impact.engine import ChangeImpactEngine, ParserBlockedError

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

        # Create a mock dart parser script to avoid parser blocked errors in non-dart tests
        self.dart_parser_dir = self.repo_root / 'tools' / 'change_impact' / 'dart_parser' / 'bin'
        self.dart_parser_dir.mkdir(parents=True)
        self.dart_parser_script = self.dart_parser_dir / 'parser.dart'
        self.dart_parser_script.write_text("void main() {}")

        # Create pubspec.yaml for dart parser
        (self.repo_root / 'tools' / 'change_impact' / 'dart_parser' / 'pubspec.yaml').write_text("name: dart_parser")

        self.engine = ChangeImpactEngine(str(self.repo_root))

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_file(self, rel_path, content=""):
        p = self.repo_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_simple_dependency(self):
        self.create_file("a.py", "def a(): pass")
        self.create_file("b.py", "import a")
        self.create_file("test_b.py", "import b")

        affected, tests = self.engine.analyze(["a.py"])
        self.assertEqual(set(affected), {"a.py", "b.py", "test_b.py"})
        self.assertEqual(set(tests), {"test_b.py"})

    def test_cyclic_imports(self):
        self.create_file("x.py", "import y")
        self.create_file("y.py", "import x")
        self.create_file("test_x.py", "import x")

        affected, tests = self.engine.analyze(["x.py"])
        self.assertEqual(set(affected), {"x.py", "y.py", "test_x.py"})
        self.assertEqual(set(tests), {"test_x.py"})

    def test_renames_and_indirect_imports(self):
        # A rename / import alias
        self.create_file("core.py", "def f(): pass")
        self.create_file("api.py", "from core import f as api_f")
        self.create_file("test_api.py", "from api import api_f")

        affected, tests = self.engine.analyze(["core.py"])
        self.assertEqual(set(affected), {"core.py", "api.py", "test_api.py"})
        self.assertEqual(set(tests), {"test_api.py"})

    def test_relative_imports(self):
        self.create_file("pkg/utils.py", "def f(): pass")
        self.create_file("pkg/__init__.py", "from . import utils")

        affected, tests = self.engine.analyze(["pkg/utils.py"])
        self.assertEqual(set(affected), {"pkg/utils.py", "pkg/__init__.py"})

    def test_syntax_errors(self):
        self.create_file("bad.py", "def bad(:")
        self.create_file("test_bad.py", "import bad")

        affected, tests = self.engine.analyze(["bad.py"])
        # bad.py won't parse properly to establish out-edges, but test_bad.py imports bad.py
        # test_bad.py parses correctly, its out-edge points to bad.py. So reverse graph has bad.py -> test_bad.py
        self.assertEqual(set(affected), {"bad.py", "test_bad.py"})
        self.assertEqual(set(tests), {"test_bad.py"})

    def test_dynamic_uncertainty(self):
        self.create_file("base.py", "")
        self.create_file("plugin.py", "importlib.import_module('dynamic')")
        self.create_file("unrelated.py", "")
        self.create_file("test_unrelated.py", "import unrelated")

        # Due to plugin.py, has_global_uncertainty becomes True.
        # This causes ALL files to be considered affected.
        affected, tests = self.engine.analyze(["base.py"])

        expected_affected = {"base.py", "plugin.py", "unrelated.py", "test_unrelated.py",
                             "tools/change_impact/dart_parser/bin/parser.dart"}

        self.assertEqual(set(affected), expected_affected)
        self.assertEqual(set(tests), {"test_unrelated.py"})

    @patch('shutil.which')
    def test_missing_capability(self, mock_which):
        mock_which.return_value = None
        self.create_file("some.dart", "import 'dart:io';")

        with self.assertRaises(ParserBlockedError):
            self.engine.analyze(["some.dart"])

    @patch('subprocess.run')
    def test_dart_imports(self, mock_run):
        # We need dart available to pass the shutil check
        # We patch subprocess.run to mock the analyzer output
        self.create_file("lib/utils.dart", "void f() {}")
        self.create_file("main.dart", "")
        self.create_file("main_test.dart", "")

        class MockCompletedProcess:
            def __init__(self, stdout):
                self.stdout = stdout

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if '--batch' in cmd:
                # Return dict mapping file paths to imports
                res = {
                    str(self.repo_root / "main.dart"): {"imports": ["package:my_pkg/utils.dart"]},
                    str(self.repo_root / "main_test.dart"): {"imports": ["main.dart"]},
                    str(self.repo_root / "lib/utils.dart"): {"imports": []}
                }
                return MockCompletedProcess(json.dumps(res))
            return MockCompletedProcess("{}")

        mock_run.side_effect = side_effect

        affected, tests = self.engine.analyze(["lib/utils.dart"])

        self.assertIn("main.dart", affected)
        self.assertIn("main_test.dart", affected)
        self.assertIn("main_test.dart", tests)
        self.assertIn("lib/utils.dart", affected)
        self.assertEqual(set(tests), {"main_test.dart"})

if __name__ == '__main__':
    unittest.main()
