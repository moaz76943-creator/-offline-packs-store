import unittest
import tempfile
import os
from pathlib import Path
from tools.change_impact.engine import DependencyEngine

class TestDependencyEngine(unittest.TestCase):
    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_temp_dir)
        self.engine = DependencyEngine(self.repo_root)

    def _cleanup_temp_dir(self):
        import shutil
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def test_python_simple_import(self):
        test_file = Path(self.repo_root) / 'main.py'
        dep_file = Path(self.repo_root) / 'utils.py'

        test_file.write_text("import utils\nutils.do_something()")
        dep_file.write_text("def do_something(): pass")

        deps, dynamic = self.engine.analyze_python(test_file)
        self.assertEqual(deps, {'utils.py'})
        self.assertFalse(dynamic)

    def test_python_import_from(self):
        test_file = Path(self.repo_root) / 'main.py'
        dep_dir = Path(self.repo_root) / 'models'
        dep_dir.mkdir()
        dep_file = dep_dir / 'user.py'

        test_file.write_text("from models.user import User")
        dep_file.write_text("class User: pass")

        deps, dynamic = self.engine.analyze_python(test_file)
        self.assertEqual(deps, {'models/user.py'})
        self.assertFalse(dynamic)

    def test_python_dynamic_import(self):
        test_file = Path(self.repo_root) / 'main.py'
        test_file.write_text("import importlib\nmod = importlib.import_module('some_module')")

        deps, dynamic = self.engine.analyze_python(test_file)
        self.assertTrue(dynamic)

    def test_python_syntax_error(self):
        test_file = Path(self.repo_root) / 'main.py'
        test_file.write_text("def foo():\n  invalid syntax here")

        deps, dynamic = self.engine.analyze_python(test_file)
        self.assertTrue(dynamic)

    def test_dart_simple_import(self):
        test_file = Path(self.repo_root) / 'main.dart'
        dep_file = Path(self.repo_root) / 'utils.dart'

        test_file.write_text("import 'utils.dart';\nvoid main() {}")
        dep_file.write_text("void doSomething() {}")

        deps, dynamic = self.engine.analyze_dart(test_file)
        self.assertEqual(deps, {'utils.dart'})
        self.assertFalse(dynamic)

    def test_dart_dynamic_import(self):
        test_file = Path(self.repo_root) / 'main.dart'
        test_file.write_text("import 'dart:mirrors';\nvoid main() {}")

        deps, dynamic = self.engine.analyze_dart(test_file)
        self.assertTrue(dynamic)

    def test_build_graph_and_impact(self):
        # A depends on B, B depends on C
        a_py = Path(self.repo_root) / 'a.py'
        b_py = Path(self.repo_root) / 'b.py'
        c_py = Path(self.repo_root) / 'c.py'
        test_b_py = Path(self.repo_root) / 'test_b.py'

        a_py.write_text("import b")
        b_py.write_text("import c\ndef b_func(): pass")
        c_py.write_text("def c_func(): pass")
        test_b_py.write_text("import b\ndef test_b_func(): b.b_func()")

        graph = self.engine.build_graph([a_py, b_py, c_py, test_b_py])

        # Test impact of changing C
        impact = self.engine.determine_impact(['c.py'], graph)
        impacted_files = set(impact['impacted_files'])
        test_ids = set(impact['test_ids'])

        self.assertEqual(impacted_files, {'a.py', 'b.py', 'c.py', 'test_b.py'})
        self.assertEqual(test_ids, {'test_b.py'})
        self.assertFalse(impact['uncertain'])

    def test_cyclic_imports(self):
        a_py = Path(self.repo_root) / 'a.py'
        b_py = Path(self.repo_root) / 'b.py'

        a_py.write_text("import b")
        b_py.write_text("import a")

        graph = self.engine.build_graph([a_py, b_py])
        impact = self.engine.determine_impact(['a.py'], graph)

        self.assertEqual(set(impact['impacted_files']), {'a.py', 'b.py'})

    def test_mixed_python_dart(self):
        py_file = Path(self.repo_root) / 'main.py'
        dart_file = Path(self.repo_root) / 'main.dart'

        py_file.write_text("print('Python')")
        dart_file.write_text("void main() { print('Dart'); }")

        graph = self.engine.build_graph([py_file, dart_file])
        impact = self.engine.determine_impact(['main.dart'], graph)

        self.assertEqual(set(impact['impacted_files']), {'main.dart'})

    def test_renames_indirect(self):
        # A imports B as b_mod, B imports C
        a_py = Path(self.repo_root) / 'a.py'
        b_py = Path(self.repo_root) / 'b.py'
        c_py = Path(self.repo_root) / 'c.py'

        a_py.write_text("import b as b_mod")
        b_py.write_text("from c import func")
        c_py.write_text("def func(): pass")

        graph = self.engine.build_graph([a_py, b_py, c_py])
        impact = self.engine.determine_impact(['c.py'], graph)

        self.assertEqual(set(impact['impacted_files']), {'a.py', 'b.py', 'c.py'})

if __name__ == '__main__':
    unittest.main()
