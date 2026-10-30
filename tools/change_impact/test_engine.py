import unittest
import os
import shutil
import tempfile
from tools.change_impact.engine import DependencyGraph, get_impact

class TestChangeImpact(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def create_file(self, path, content):
        full_path = os.path.join(self.test_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)

    def test_python_cyclic_imports(self):
        self.create_file('a.py', 'import b')
        self.create_file('b.py', 'import a')
        self.create_file('test_a.py', 'import a')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        impacted_files, impacted_tests = graph.get_impacted_tests(['a.py'])
        self.assertIn('b.py', impacted_files)
        self.assertIn('test_a.py', impacted_tests)

    def test_indirect_imports(self):
        self.create_file('base.py', 'def foo(): pass')
        self.create_file('middle.py', 'import base')
        self.create_file('test_middle.py', 'import middle')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        impacted_files, impacted_tests = graph.get_impacted_tests(['base.py'])
        self.assertIn('middle.py', impacted_files)
        self.assertIn('test_middle.py', impacted_tests)

    def test_dynamic_imports_uncertainty(self):
        self.create_file('dynamic.py', 'importlib.import_module("foo")')
        self.create_file('test_dynamic.py', 'import dynamic')
        self.create_file('unrelated.py', 'pass')
        self.create_file('test_unrelated.py', 'import unrelated')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        # When dynamic is changed, uncertainty should widen scope
        impacted_files, impacted_tests = graph.get_impacted_tests(['dynamic.py'])
        self.assertIn('test_unrelated.py', impacted_tests)

    def test_syntax_error(self):
        self.create_file('bad.py', 'this is not valid python')
        self.create_file('test_bad.py', 'import bad')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        # Syntax error should cause uncertainty, widening scope
        impacted_files, impacted_tests = graph.get_impacted_tests(['bad.py'])
        self.assertIn('test_bad.py', impacted_tests)
        self.assertIn('bad.py', impacted_files)

    def test_dart_imports(self):
        self.create_file('lib/a.dart', 'import "b.dart";')
        self.create_file('lib/b.dart', 'void main() {}')
        self.create_file('test/a_test.dart', 'import "../lib/a.dart";')

        # We also need a pubspec.yaml for dart parser to be happy
        self.create_file('pubspec.yaml', 'name: test_pkg\nenvironment:\n  sdk: ">=3.0.0 <4.0.0"')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        impacted_files, impacted_tests = graph.get_impacted_tests(['lib/b.dart'])
        self.assertIn('lib/a.dart', impacted_files)
        self.assertIn('test/a_test.dart', impacted_tests)

    def test_mixed_tree(self):
        self.create_file('pylib.py', 'pass')
        self.create_file('test_pylib.py', 'import pylib')
        self.create_file('lib/dartlib.dart', 'void main() {}')
        self.create_file('test/dartlib_test.dart', 'import "../lib/dartlib.dart";')

        graph = DependencyGraph(self.test_dir)
        graph.build_graph()

        p_files, p_tests = graph.get_impacted_tests(['pylib.py'])
        self.assertIn('test_pylib.py', p_tests)
        self.assertNotIn('test/dartlib_test.dart', p_tests)

        d_files, d_tests = graph.get_impacted_tests(['lib/dartlib.dart'])
        self.assertIn('test/dartlib_test.dart', d_tests)
        self.assertNotIn('test_pylib.py', d_tests)

if __name__ == '__main__':
    unittest.main()
