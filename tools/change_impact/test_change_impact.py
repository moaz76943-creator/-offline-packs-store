import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from engine import DependencyEngine

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.manifest_path = self.temp_dir / "manifest.json"
        self.manifest_data = {
            "test_core": ["core.py"],
            "test_utils": ["utils.py"],
            "test_dart_core": ["core.dart"],
            "test_mixed": ["mixed_main.py", "mixed.dart"]
        }
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_basic_python_dependency(self):
        # core.py depends on utils.py
        with open(self.temp_dir / "utils.py", "w") as f:
            f.write("def helper(): pass\n")
        with open(self.temp_dir / "core.py", "w") as f:
            f.write("import utils\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["utils.py"])
        self.assertIn("test_core", impacted)
        self.assertIn("test_utils", impacted)

    def test_indirect_import(self):
        # main.py -> core.py -> utils.py
        with open(self.temp_dir / "utils.py", "w") as f:
            f.write("def helper(): pass\n")
        with open(self.temp_dir / "core.py", "w") as f:
            f.write("import utils\n")
        with open(self.temp_dir / "main.py", "w") as f:
            f.write("from core import something\n")

        # Update manifest
        self.manifest_data["test_main"] = ["main.py"]
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["utils.py"])
        self.assertIn("test_core", impacted)
        self.assertIn("test_main", impacted)

    def test_cyclic_imports(self):
        # a.py -> b.py -> a.py
        with open(self.temp_dir / "a.py", "w") as f:
            f.write("import b\n")
        with open(self.temp_dir / "b.py", "w") as f:
            f.write("import a\n")

        self.manifest_data["test_a"] = ["a.py"]
        self.manifest_data["test_b"] = ["b.py"]
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["a.py"])
        self.assertIn("test_a", impacted)
        self.assertIn("test_b", impacted)

    def test_dynamic_import_widening(self):
        with open(self.temp_dir / "core.py", "w") as f:
            f.write("module_name = 'utils'\n__import__(module_name)\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        self.assertTrue(engine.dynamic_imports_detected)

        # When dynamic imports are detected, all tests are returned to avoid false cleans
        impacted, _ = engine.get_impacted_tests(["some_unrelated_file.py"])
        self.assertEqual(len(impacted), len(self.manifest_data))

    def test_syntax_errors_ignored(self):
        with open(self.temp_dir / "broken.py", "w") as f:
            f.write("def broken(:\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        # Should not raise SyntaxError
        engine.build_graph()

    def test_dart_basic_dependency(self):
        with open(self.temp_dir / "utils.dart", "w") as f:
            f.write("void helper() {}\n")
        with open(self.temp_dir / "core.dart", "w") as f:
            f.write("import 'utils.dart';\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["utils.dart"])
        self.assertIn("test_dart_core", impacted)

    def test_dart_dynamic_import_widening(self):
        with open(self.temp_dir / "core.dart", "w") as f:
            f.write("import 'dart:mirrors';\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        self.assertTrue(engine.dynamic_imports_detected)
        impacted, _ = engine.get_impacted_tests(["core.dart"])
        self.assertEqual(len(impacted), len(self.manifest_data))

    def test_renames(self):
        # A rename means a file was changed (added or modified).
        # The AST graph will pick it up correctly.
        with open(self.temp_dir / "old_name.py", "w") as f:
            f.write("def old(): pass\n")
        with open(self.temp_dir / "new_name.py", "w") as f:
            f.write("import old_name\n")

        self.manifest_data["test_new"] = ["new_name.py"]
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["old_name.py"])
        self.assertIn("test_new", impacted)

    def test_mixed_python_dart_source_tree(self):
        # Python core uses Python utils
        with open(self.temp_dir / "utils.py", "w") as f:
            f.write("def helper(): pass\n")
        with open(self.temp_dir / "mixed_main.py", "w") as f:
            f.write("import utils\n")

        # Dart core uses Dart utils
        with open(self.temp_dir / "utils.dart", "w") as f:
            f.write("void helper() {}\n")
        with open(self.temp_dir / "mixed.dart", "w") as f:
            f.write("import 'utils.dart';\n")

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted_python, _ = engine.get_impacted_tests(["utils.py"])
        self.assertIn("test_mixed", impacted_python)

        impacted_dart, _ = engine.get_impacted_tests(["utils.dart"])
        self.assertIn("test_mixed", impacted_dart)

    def test_relative_import(self):
        # Create a nested package
        pkg_dir = self.temp_dir / "mypackage"
        pkg_dir.mkdir()
        with open(pkg_dir / "__init__.py", "w") as f:
            f.write("from . import utils\n")
        with open(pkg_dir / "utils.py", "w") as f:
            f.write("def helper(): pass\n")

        self.manifest_data["test_pkg"] = ["mypackage/__init__.py"]
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

        engine = DependencyEngine(str(self.temp_dir))
        engine.load_manifest(str(self.manifest_path))
        engine.build_graph()

        impacted, _ = engine.get_impacted_tests(["mypackage/utils.py"])
        self.assertIn("test_pkg", impacted)

if __name__ == '__main__':
    unittest.main()
