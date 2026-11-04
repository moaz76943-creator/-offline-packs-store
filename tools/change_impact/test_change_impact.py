import unittest
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.change_impact.engine import analyze_impact, get_module_name, extract_dart_deps

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_file(self, rel_path, content):
        file_path = self.repo_root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)

    def test_simple_dependency(self):
        self.create_file("module_a.py", "def a(): pass")
        self.create_file("module_b.py", "import module_a\ndef b(): module_a.a()")
        self.create_file("test_module_b.py", "import module_b\ndef test_b(): pass")

        impact = analyze_impact(self.repo_root, ["module_a.py"])
        self.assertIn("module_b.py", impact["affected_files"])
        self.assertIn("test_module_b.py", impact["affected_tests"])

    def test_cyclic_imports(self):
        self.create_file("cycle_a.py", "import cycle_b")
        self.create_file("cycle_b.py", "import cycle_a")

        impact = analyze_impact(self.repo_root, ["cycle_a.py"])
        self.assertIn("cycle_b.py", impact["affected_files"])

    def test_indirect_imports(self):
        self.create_file("base.py", "def func(): pass")
        self.create_file("middle.py", "from base import func")
        self.create_file("test_top.py", "import middle")

        impact = analyze_impact(self.repo_root, ["base.py"])
        self.assertIn("middle.py", impact["affected_files"])
        self.assertIn("test_top.py", impact["affected_tests"])

    def test_dynamic_imports_widens_scope(self):
        self.create_file("dynamic.py", "__import__('some_module')")
        self.create_file("test_unrelated.py", "def test(): pass")
        self.create_file("test_related.py", "import dynamic")

        impact = analyze_impact(self.repo_root, ["dynamic.py"])
        # dynamic imports should widen the test scope to all tests
        self.assertIn("test_unrelated.py", impact["affected_tests"])
        self.assertIn("test_related.py", impact["affected_tests"])

    def test_syntax_error_widens_scope(self):
        self.create_file("bad_syntax.py", "def broken( \n")
        self.create_file("test_unrelated.py", "def test(): pass")

        impact = analyze_impact(self.repo_root, ["bad_syntax.py"])
        self.assertIn("test_unrelated.py", impact["affected_tests"])

    @patch("subprocess.run")
    def test_missing_dart_parser(self, mock_run):
        # We need a Dart file to trigger Dart parsing
        self.create_file("app.dart", "import 'lib.dart';")

        mock_result = MagicMock()
        mock_result.returncode = 254
        mock_result.stderr = "Could not resolve the package 'analyzer'"
        mock_run.return_value = mock_result

        # Ensure the script exists in mock so it tries to run
        tools_dir = self.repo_root / "tools" / "change_impact"
        tools_dir.mkdir(parents=True, exist_ok=True)
        (tools_dir / "parse_dart.dart").touch()

        with self.assertRaises(Exception) as context:
            analyze_impact(self.repo_root, ["app.dart"])

        self.assertEqual(str(context.exception), "BLOCKED: Missing parser capability")

    @patch("subprocess.run")
    def test_mixed_source_trees(self, mock_run):
        self.create_file("py_mod.py", "def py(): pass")
        self.create_file("test_py_mod.py", "import py_mod")
        self.create_file("dart_lib.dart", "class Lib {}")
        self.create_file("dart_app.dart", "import 'dart_lib.dart';")

        # Create dummy parser script
        tools_dir = self.repo_root / "tools" / "change_impact"
        tools_dir.mkdir(parents=True, exist_ok=True)
        (tools_dir / "parse_dart.dart").touch()

        def side_effect(args, **kwargs):
            mock_res = MagicMock()
            mock_res.returncode = 0
            if "dart_app.dart" in args[-1]:
                mock_res.stdout = json.dumps({"deps": ["dart_lib.dart"], "dynamic": False})
            else:
                mock_res.stdout = json.dumps({"deps": [], "dynamic": False})
            return mock_res

        mock_run.side_effect = side_effect

        impact = analyze_impact(self.repo_root, ["dart_lib.dart"])
        self.assertIn("dart_app.dart", impact["affected_files"])
        self.assertNotIn("test_py_mod.py", impact["affected_tests"])

        impact_py = analyze_impact(self.repo_root, ["py_mod.py"])
        self.assertIn("test_py_mod.py", impact_py["affected_tests"])


    def test_renames(self):
        self.create_file("module_c.py", "def c(): pass")
        self.create_file("module_d.py", "import module_c as custom_c\ndef d(): custom_c.c()")
        self.create_file("test_module_d.py", "import module_d\ndef test_d(): pass")

        impact = analyze_impact(self.repo_root, ["module_c.py"])
        self.assertIn("module_d.py", impact["affected_files"])
        self.assertIn("test_module_d.py", impact["affected_tests"])
