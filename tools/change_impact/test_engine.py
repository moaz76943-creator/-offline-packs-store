import unittest
import os
import tempfile
import shutil
import sys
import subprocess
from io import StringIO
import unittest.mock as mock

# Add repo root to python path to import engine
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from tools.change_impact.engine import ChangeImpactEngine

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_python_direct_dependency(self):
        # Create a simple python dependency
        os.makedirs(os.path.join(self.test_dir, 'module_a'))
        with open(os.path.join(self.test_dir, 'module_a', '__init__.py'), 'w') as f:
            f.write("")
        with open(os.path.join(self.test_dir, 'module_a', 'core.py'), 'w') as f:
            f.write("def foo(): return 1\n")

        with open(os.path.join(self.test_dir, 'main.py'), 'w') as f:
            f.write("from module_a import core\ncore.foo()\n")

        with open(os.path.join(self.test_dir, 'test_main.py'), 'w') as f:
            f.write("import main\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        impacted_files, tests = engine.get_impacted_tests([os.path.join('module_a', 'core.py')])
        self.assertIn('main.py', impacted_files)
        self.assertIn('test_main.py', tests)

    def test_dynamic_import_widening(self):
        with open(os.path.join(self.test_dir, 'dynamic.py'), 'w') as f:
            f.write("import importlib\nmodule = importlib.import_module('some_module')\n")

        with open(os.path.join(self.test_dir, 'test_dynamic.py'), 'w') as f:
            f.write("import dynamic\n")

        with open(os.path.join(self.test_dir, 'test_other.py'), 'w') as f:
            f.write("def test_nothing(): pass\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        # dynamic.py has a dynamic import. Changing it should trigger all tests.
        impacted_files, tests = engine.get_impacted_tests(['dynamic.py'])
        self.assertIn('test_dynamic.py', tests)
        self.assertIn('test_other.py', tests)

    def test_dart_direct_dependency(self):
        os.makedirs(os.path.join(self.test_dir, 'dart_pkg'))
        with open(os.path.join(self.test_dir, 'dart_pkg', 'core.dart'), 'w') as f:
            f.write("void foo() {}\n")

        with open(os.path.join(self.test_dir, 'dart_pkg', 'main.dart'), 'w') as f:
            f.write("import 'core.dart';\nvoid main() { foo(); }\n")

        with open(os.path.join(self.test_dir, 'dart_pkg', 'test_main.dart'), 'w') as f:
            f.write("import 'main.dart';\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        impacted_files, tests = engine.get_impacted_tests([os.path.join('dart_pkg', 'core.dart')])
        self.assertIn(os.path.join('dart_pkg', 'main.dart'), impacted_files)
        self.assertIn(os.path.join('dart_pkg', 'test_main.dart'), tests)

    def test_python_cyclic_import(self):
        with open(os.path.join(self.test_dir, 'cycle_a.py'), 'w') as f:
            f.write("import cycle_b\n")
        with open(os.path.join(self.test_dir, 'cycle_b.py'), 'w') as f:
            f.write("import cycle_a\n")
        with open(os.path.join(self.test_dir, 'test_cycle.py'), 'w') as f:
            f.write("import cycle_a\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        impacted_files, tests = engine.get_impacted_tests(['cycle_b.py'])
        self.assertIn('cycle_a.py', impacted_files)
        self.assertIn('test_cycle.py', tests)

    def test_syntax_error_handled(self):
        with open(os.path.join(self.test_dir, 'bad_syntax.py'), 'w') as f:
            f.write("this is not python\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()
        # Should not crash
        impacted_files, tests = engine.get_impacted_tests(['bad_syntax.py'])
        self.assertIn('bad_syntax.py', impacted_files)

    def test_python_dart_mixed(self):
        os.makedirs(os.path.join(self.test_dir, 'mixed'))
        with open(os.path.join(self.test_dir, 'mixed', 'core.py'), 'w') as f:
            f.write("def foo(): return 1\n")
        with open(os.path.join(self.test_dir, 'mixed', 'main.py'), 'w') as f:
            f.write("import core\n")
        with open(os.path.join(self.test_dir, 'mixed', 'test_main.py'), 'w') as f:
            f.write("import main\n")

        with open(os.path.join(self.test_dir, 'mixed', 'core.dart'), 'w') as f:
            f.write("void bar() {}\n")
        with open(os.path.join(self.test_dir, 'mixed', 'main.dart'), 'w') as f:
            f.write("import 'core.dart';\nvoid main() { bar(); }\n")
        with open(os.path.join(self.test_dir, 'mixed', 'test_main.dart'), 'w') as f:
            f.write("import 'main.dart';\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        impacted, tests = engine.get_impacted_tests([os.path.join('mixed', 'core.py')])
        self.assertIn(os.path.join('mixed', 'test_main.py'), tests)
        self.assertNotIn(os.path.join('mixed', 'test_main.dart'), tests)

        impacted, tests = engine.get_impacted_tests([os.path.join('mixed', 'core.dart')])
        self.assertIn(os.path.join('mixed', 'test_main.dart'), tests)
        self.assertNotIn(os.path.join('mixed', 'test_main.py'), tests)

    def test_python_rename_simulated(self):
        os.makedirs(os.path.join(self.test_dir, 'rename_test'))
        with open(os.path.join(self.test_dir, 'rename_test', 'old_name.py'), 'w') as f:
            f.write("def foo(): pass\n")
        with open(os.path.join(self.test_dir, 'rename_test', 'consumer.py'), 'w') as f:
            f.write("import old_name\n")
        with open(os.path.join(self.test_dir, 'rename_test', 'test_consumer.py'), 'w') as f:
            f.write("import consumer\n")

        engine = ChangeImpactEngine(self.test_dir)
        engine.analyze()

        impacted, tests = engine.get_impacted_tests([os.path.join('rename_test', 'old_name.py')])
        self.assertIn(os.path.join('rename_test', 'test_consumer.py'), tests)

    def test_missing_dart_capability(self):
        engine = ChangeImpactEngine(self.test_dir)
        with mock.patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'dart')):
            old_stdout = sys.stdout
            sys.stdout = mystdout = StringIO()
            try:
                engine.parse_dart('some_file.dart')
            finally:
                sys.stdout = old_stdout
            self.assertIn("BLOCKED", mystdout.getvalue())

if __name__ == '__main__':
    unittest.main()
