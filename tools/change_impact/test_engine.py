import unittest
import os
import json
import tempfile
import shutil
from pathlib import Path
from engine import DependencyEngine

class TestDependencyEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_root = Path(self.temp_dir)
        self.engine = DependencyEngine(self.repo_root)

        # Override the engine_dir so dart parsing uses the real dart script
        # rather than expecting it in the temp directory.
        self.real_engine_dir = Path(__file__).parent.resolve()
        self.engine.engine_dir = self.real_engine_dir

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_python_parsing(self):
        test_py = self.repo_root / "test_dummy.py"
        test_py.write_text("import os\nfrom pathlib import Path\n__import__('sys')\n")

        self.engine.parse_python_file(test_py)
        rel_path = "test_dummy.py"

        self.assertIn(rel_path, self.engine.graph)
        deps = self.engine.graph[rel_path]
        self.assertIn("os", deps)
        self.assertIn("pathlib.Path", deps)
        self.assertIn(rel_path, self.engine.uncertain_nodes)

    def test_dart_parsing(self):
        test_dart = self.repo_root / "test_dummy.dart"
        test_dart.write_text("import 'dart:io';\nimport 'package:analyzer/analyzer.dart';\nvoid main(){}")

        self.engine.parse_dart_file(test_dart)
        rel_path = "test_dummy.dart"

        self.assertIn(rel_path, self.engine.graph)
        deps = self.engine.graph[rel_path]
        self.assertIn("dart:io", deps)
        self.assertIn("package:analyzer/analyzer.dart", deps)
        self.assertNotIn(rel_path, self.engine.uncertain_nodes)

    def test_dart_syntax_error(self):
        test_dart = self.repo_root / "test_error.dart"
        test_dart.write_text("import 'dart:io';\nvoid main() {")

        self.engine.parse_dart_file(test_dart)
        rel_path = "test_error.dart"

        self.assertIn(rel_path, self.engine.uncertain_nodes)

    def test_build_graph_and_impact(self):
        # Create actual files so the resolver works
        a_py = self.repo_root / "a.py"
        b_py = self.repo_root / "b.py"
        c_py = self.repo_root / "c.py"

        c_py.write_text("def c_func(): pass\n")
        b_py.write_text("from c import c_func\n")
        a_py.write_text("import b\n")

        self.engine.parse_python_file(c_py)
        self.engine.parse_python_file(b_py)
        self.engine.parse_python_file(a_py)

        self.engine.build_graph()

        self.assertIn("c.py", self.engine.reverse_graph)
        self.assertIn("b.py", self.engine.reverse_graph["c.py"])
        self.assertIn("a.py", self.engine.reverse_graph["b.py"])

        impacted = self.engine.calculate_impact(["c.py"])
        self.assertIn("c.py", impacted)
        self.assertIn("b.py", impacted)
        self.assertIn("a.py", impacted)

    def test_dynamic_widen(self):
        c_py = self.repo_root / "c.py"
        c_py.write_text("__import__('sys')\n")
        d_py = self.repo_root / "d.py"
        d_py.write_text("pass\n")

        self.engine.parse_python_file(c_py)
        self.engine.parse_python_file(d_py)

        self.engine.build_graph()

        impacted = self.engine.calculate_impact(["c.py"])
        self.assertIn("c.py", impacted)
        self.assertIn("d.py", impacted)

    def test_cyclic_imports(self):
        x_py = self.repo_root / "x.py"
        y_py = self.repo_root / "y.py"

        x_py.write_text("import y\n")
        y_py.write_text("import x\n")

        self.engine.parse_python_file(x_py)
        self.engine.parse_python_file(y_py)

        self.engine.build_graph()

        self.assertIn("x.py", self.engine.reverse_graph["y.py"])
        self.assertIn("y.py", self.engine.reverse_graph["x.py"])

        impacted = self.engine.calculate_impact(["x.py"])
        self.assertIn("x.py", impacted)
        self.assertIn("y.py", impacted)

    def test_indirect_imports(self):
        core_dir = self.repo_root / "core"
        core_dir.mkdir()
        utils_py = core_dir / "utils.py"
        utils_py.write_text("def helper(): pass\n")

        main_py = self.repo_root / "main.py"
        main_py.write_text("from core.utils import helper\n")

        self.engine.parse_python_file(utils_py)
        self.engine.parse_python_file(main_py)

        self.engine.build_graph()

        # main depends on core/utils.py
        self.assertIn("main.py", self.engine.reverse_graph["core/utils.py"])

    def test_mixed_tree(self):
        py_file = self.repo_root / "script.py"
        dart_file = self.repo_root / "app.dart"

        py_file.write_text("import os\n")
        dart_file.write_text("import 'dart:io';\n")

        self.engine.parse_python_file(py_file)
        self.engine.parse_dart_file(dart_file)

        self.engine.build_graph()

        self.assertIn("script.py", self.engine.graph)
        self.assertIn("app.dart", self.engine.graph)

    def test_renames(self):
        a_py = self.repo_root / "a.py"
        b_py = self.repo_root / "b.py"

        b_py.write_text("def x(): pass\n")
        a_py.write_text("from b import x as y\n")

        self.engine.parse_python_file(b_py)
        self.engine.parse_python_file(a_py)

        self.engine.build_graph()

        self.assertIn("a.py", self.engine.reverse_graph["b.py"])

        impacted = self.engine.calculate_impact(["b.py"])
        self.assertIn("a.py", impacted)
        self.assertIn("b.py", impacted)

    def test_relative_imports(self):
        core_dir = self.repo_root / "core"
        core_dir.mkdir()
        utils_py = core_dir / "utils.py"
        main_py = core_dir / "main.py"

        utils_py.write_text("def helper(): pass\n")
        main_py.write_text("from .utils import helper\n")

        self.engine.parse_python_file(utils_py)
        self.engine.parse_python_file(main_py)

        self.engine.build_graph()

        # main.py depends on utils.py via relative import
        self.assertIn("core/main.py", self.engine.reverse_graph["core/utils.py"])

if __name__ == "__main__":
    unittest.main()
