import unittest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import DependencyEngine

class TestDependencyEngine(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.engine = DependencyEngine(self.repo_root)

    def test_python_parsing(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"import os\nfrom sys import argv\n")
            path = f.name

        try:
            imports, reflection, syntax_err = self.engine._parse_python_file(path)
            self.assertIn("os", imports)
            self.assertIn("sys", imports)
            self.assertFalse(reflection)
            self.assertFalse(syntax_err)
        finally:
            os.remove(path)

    def test_dart_parsing(self):
        with tempfile.NamedTemporaryFile(suffix=".dart", delete=False) as f:
            f.write(b"import 'dart:io';\nimport 'package:foo/foo.dart';\nvoid main() {}")
            path = f.name

        try:
            imports, reflection, syntax_err = self.engine._parse_dart_file(path)
            self.assertIn("dart:io", imports)
            self.assertIn("package:foo/foo.dart", imports)
            self.assertFalse(reflection)
            self.assertFalse(syntax_err)
        finally:
            os.remove(path)

    def test_dynamic_uncertainty_widen(self):
        # We simulate a dynamic file that uses reflection.
        # By adding a file using reflection and another depending on it, or changed_file uses reflection,
        # map_impact should widen the scope.

        # Manually construct a graph
        self.engine.forward_graph = {
            "a.py": set(["b.py"]),
            "b.py": set(),
            "test_b.py": set(["b.py"]),
            "test_a.py": set(["a.py"]),
            "c.py": set(),
            "test_c.py": set(["c.py"])
        }
        self.engine.reflection_nodes = set(["b.py"])

        impact = self.engine.map_impact(["b.py"])
        self.assertTrue(impact["widened"])
        self.assertIn("test_c.py", impact["affected_tests"])
        self.assertIn("c.py", impact["affected_files"])

    def test_cyclic_imports(self):
        self.engine.forward_graph = {
            "cycle1.py": set(["cycle2.py"]),
            "cycle2.py": set(["cycle1.py"]),
            "test_cycle.py": set(["cycle1.py"])
        }
        impact = self.engine.map_impact(["cycle2.py"])
        self.assertFalse(impact["widened"])
        self.assertIn("cycle1.py", impact["affected_files"])
        self.assertIn("cycle2.py", impact["affected_files"])
        self.assertIn("test_cycle.py", impact["affected_tests"])

    def test_syntax_error(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"import from nowhere\n")
            path = f.name

        try:
            imports, reflection, syntax_err = self.engine._parse_python_file(path)
            self.assertTrue(syntax_err)
        finally:
            os.remove(path)

    def test_missing_parser_blocked(self):
        # Temporarily hide dart parser
        original_path = self.engine.dart_parser_path
        self.engine.dart_parser_path = "/nonexistent/parser.dart"
        with self.assertRaises(RuntimeError) as context:
            self.engine._parse_dart_file("some_file.dart")
        self.assertIn("BLOCKED", str(context.exception))
        self.engine.dart_parser_path = original_path

    def test_indirect_imports(self):
        self.engine.forward_graph = {
            "leaf.py": set(),
            "mid.py": set(["leaf.py"]),
            "root.py": set(["mid.py"]),
            "test_root.py": set(["root.py"])
        }
        impact = self.engine.map_impact(["leaf.py"])
        self.assertFalse(impact["widened"])
        self.assertIn("root.py", impact["affected_files"])
        self.assertIn("test_root.py", impact["affected_tests"])

    def test_repo_root_unavailable(self):
        with self.assertRaises(RuntimeError) as context:
            DependencyEngine("/non/existent/path/xyz123")
        self.assertIn("Repository access is unavailable", str(context.exception))

    def test_rename(self):
        # We simulate a rename by passing a renamed file path to map_impact.
        self.engine.forward_graph = {
            "old_name.py": set(["dep.py"]),
            "dep.py": set(),
            "test_dep.py": set(["dep.py"])
        }
        # Rename old_name.py -> new_name.py, so new_name.py is passed
        impact = self.engine.map_impact(["new_name.py", "old_name.py"])
        self.assertIn("new_name.py", impact["affected_files"])
        self.assertIn("old_name.py", impact["affected_files"])

    def test_mixed_python_dart(self):
        self.engine.forward_graph = {
            "app.dart": set(["lib.dart"]),
            "lib.dart": set(),
            "script.py": set(["app.dart"]), # somewhat contrived but proves mixed trees work in map_impact
            "test_script.py": set(["script.py"])
        }
        impact = self.engine.map_impact(["lib.dart"])
        self.assertIn("app.dart", impact["affected_files"])
        self.assertIn("script.py", impact["affected_files"])
        self.assertIn("test_script.py", impact["affected_tests"])

if __name__ == '__main__':
    unittest.main()
