import unittest
import os
import json
import tempfile
from pathlib import Path
from tools.change_impact.engine import DependencyEngine

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path.cwd()
        self.engine = DependencyEngine(self.repo_root)
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.repo_root)
        self.dummy_base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_basic_python_import(self):
        dummy_dir = self.dummy_base / "dummy"
        dummy_dir.mkdir(exist_ok=True)
        rel_a = str((dummy_dir / "a.py").relative_to(self.repo_root))
        rel_b = str((dummy_dir / "b.py").relative_to(self.repo_root))

        module_path = ".".join(Path(rel_b).with_suffix('').parts)

        (dummy_dir / "a.py").write_text(f"import {module_path}")
        (dummy_dir / "b.py").write_text("def foo(): pass")

        self.engine.extract_python(dummy_dir / "a.py")
        self.engine.extract_python(dummy_dir / "b.py")

        self.assertIn(rel_b, self.engine.graph[rel_a])

    def test_syntax_error_widens_scope(self):
        dummy_dir = self.dummy_base / "dummy2"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "err.py").write_text("def invalid syntax")
        rel_err = str((dummy_dir / "err.py").relative_to(self.repo_root))

        self.engine.extract_python(dummy_dir / "err.py")
        self.assertIn(rel_err, self.engine.uncertain_modules)

        impact = self.engine.map_impact([rel_err])
        from tools.ci_policy.run_scoped_pr_tests import ORDER
        self.assertEqual(impact, list(ORDER))

    def test_dynamic_import_widens_scope(self):
        dummy_dir = self.dummy_base / "dummy3"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "dyn.py").write_text("import importlib\nimportlib.import_module('b')")
        rel_dyn = str((dummy_dir / "dyn.py").relative_to(self.repo_root))

        self.engine.extract_python(dummy_dir / "dyn.py")
        self.assertIn(rel_dyn, self.engine.uncertain_modules)

    def test_dart_syntax_error(self):
        dummy_dir = self.dummy_base / "dummy_dart"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "err.dart").write_text("void main() { invalid syntax }")
        rel_err = str((dummy_dir / "err.dart").relative_to(self.repo_root))

        self.engine.extract_dart(dummy_dir / "err.dart")
        self.assertIn(rel_err, self.engine.uncertain_modules)

    def test_cyclic_imports(self):
        dummy_dir = self.dummy_base / "dummy_cycle"
        dummy_dir.mkdir(exist_ok=True)

        rel_c1 = str((dummy_dir / "c1.py").relative_to(self.repo_root))
        rel_c2 = str((dummy_dir / "c2.py").relative_to(self.repo_root))

        mod_c1 = ".".join(Path(rel_c1).with_suffix('').parts)
        mod_c2 = ".".join(Path(rel_c2).with_suffix('').parts)

        (dummy_dir / "c1.py").write_text(f"import {mod_c2}")
        (dummy_dir / "c2.py").write_text(f"import {mod_c1}")

        self.engine.extract_python(dummy_dir / "c1.py")
        self.engine.extract_python(dummy_dir / "c2.py")

        self.assertIn(rel_c2, self.engine.graph[rel_c1])
        self.assertIn(rel_c1, self.engine.graph[rel_c2])

    def test_mixed_python_dart(self):
        dummy_dir = self.dummy_base / "dummy_mixed"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "a.py").write_text("print('python')")
        (dummy_dir / "b.dart").write_text("import 'c.dart';\nvoid main(){}")
        (dummy_dir / "c.dart").write_text("void foo(){}")

        rel_b = str((dummy_dir / "b.dart").relative_to(self.repo_root))
        rel_c = str((dummy_dir / "c.dart").relative_to(self.repo_root))

        self.engine.extract_python(dummy_dir / "a.py")
        self.engine.extract_dart(dummy_dir / "b.dart")
        self.engine.extract_dart(dummy_dir / "c.dart")

        self.assertIn(rel_c, self.engine.graph[rel_b])

    def test_renames_or_missing_files(self):
        dummy_dir = self.dummy_base / "dummy_rename"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "a.py").write_text("import missing_file")
        rel_a = str((dummy_dir / "a.py").relative_to(self.repo_root))

        self.engine.extract_python(dummy_dir / "a.py")
        self.assertEqual(len(self.engine.graph[rel_a]), 0)

    def test_indirect_imports(self):
        dummy_dir = self.dummy_base / "dummy_indirect"
        dummy_dir.mkdir(exist_ok=True)

        rel_a = str((dummy_dir / "a.py").relative_to(self.repo_root))
        rel_b = str((dummy_dir / "b.py").relative_to(self.repo_root))
        rel_c = str((dummy_dir / "c.py").relative_to(self.repo_root))

        mod_b = ".".join(Path(rel_b).with_suffix('').parts)
        mod_c = ".".join(Path(rel_c).with_suffix('').parts)

        (dummy_dir / "a.py").write_text(f"import {mod_b}")
        (dummy_dir / "b.py").write_text(f"import {mod_c}")
        (dummy_dir / "c.py").write_text("def foo(): pass")

        self.engine.extract_python(dummy_dir / "a.py")
        self.engine.extract_python(dummy_dir / "b.py")
        self.engine.extract_python(dummy_dir / "c.py")

        impact = self.engine.map_impact([rel_c])
        self.assertIsInstance(impact, list)

    def test_relative_import_from(self):
        dummy_dir = self.dummy_base / "dummy_rel"
        dummy_dir.mkdir(exist_ok=True)
        (dummy_dir / "a.py").write_text("from . import b\nfrom .c import d")
        (dummy_dir / "b.py").write_text("def foo(): pass")
        (dummy_dir / "c.py").write_text("def d(): pass")

        rel_a = str((dummy_dir / "a.py").relative_to(self.repo_root))
        rel_b = str((dummy_dir / "b.py").relative_to(self.repo_root))
        rel_c = str((dummy_dir / "c.py").relative_to(self.repo_root))

        self.engine.extract_python(dummy_dir / "a.py")
        self.engine.extract_python(dummy_dir / "b.py")
        self.engine.extract_python(dummy_dir / "c.py")

        self.assertIn(rel_b, self.engine.graph[rel_a])
        self.assertIn(rel_c, self.engine.graph[rel_a])

if __name__ == '__main__':
    unittest.main()
