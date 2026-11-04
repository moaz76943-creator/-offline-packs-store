import unittest
import os
import sys
import subprocess
from pathlib import Path
import tempfile
import io

from tools.change_impact.engine import build_dependency_graph, compute_impact, find_all_tests

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        def create_file(path_str, content):
            p = self.root / path_str
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, 'w') as f:
                f.write(content)

        # Test 1: Cyclic imports (Python)
        create_file("mod_a.py", "import mod_b\ndef a(): pass")
        create_file("mod_b.py", "import mod_a\ndef b(): pass")
        create_file("test_ab.py", "import mod_a\nimport mod_b")

        # Test 2: File renames / indirect dependencies (Python)
        create_file("core/__init__.py", "")
        create_file("core/util.py", "def util(): pass")
        create_file("core/wrapper.py", "from .util import util")
        create_file("core/test_wrapper.py", "from .wrapper import util")

        # Test 3: Syntax error widens scope (Python)
        create_file("bad_syntax.py", "def foo(::)")
        create_file("test_bad.py", "import bad_syntax")

        # Test 4: Dynamic imports widens scope (Python)
        create_file("dyn.py", "import importlib\nimportlib.import_module('sys')")
        create_file("test_dyn.py", "import dyn")

        # Test 5: Dart files with package import
        create_file("pubspec.yaml", "name: my_package\n")
        create_file("lib/src/util.dart", "void util() {}")
        create_file("lib/wrapper.dart", "import 'src/util.dart';")
        create_file("test/wrapper_test.dart", "import 'package:my_package/wrapper.dart';")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cyclic_imports(self):
        graph, dyn = build_dependency_graph(self.root)
        all_tests = find_all_tests(self.root)

        affected, tests = compute_impact(graph, dyn, ["mod_a.py"], all_tests)

        self.assertIn("mod_b.py", affected)
        self.assertIn("test_ab.py", tests)

    def test_indirect_dependencies(self):
        graph, dyn = build_dependency_graph(self.root)
        all_tests = find_all_tests(self.root)

        affected, tests = compute_impact(graph, dyn, ["core/util.py"], all_tests)

        self.assertIn("core/wrapper.py", affected)
        self.assertIn("core/test_wrapper.py", tests)

    def test_syntax_error_widens_scope(self):
        graph, dyn = build_dependency_graph(self.root)
        all_tests = find_all_tests(self.root)

        affected, tests = compute_impact(graph, dyn, ["bad_syntax.py"], all_tests)
        self.assertTrue(dyn["bad_syntax.py"])
        self.assertEqual(sorted(tests), sorted(all_tests))

    def test_dynamic_imports_widens_scope(self):
        graph, dyn = build_dependency_graph(self.root)
        all_tests = find_all_tests(self.root)

        affected, tests = compute_impact(graph, dyn, ["dyn.py"], all_tests)
        self.assertTrue(dyn["dyn.py"])
        self.assertEqual(sorted(tests), sorted(all_tests))

    def test_dart_dependencies(self):
        graph, dyn = build_dependency_graph(self.root)
        all_tests = find_all_tests(self.root)

        affected, tests = compute_impact(graph, dyn, ["lib/src/util.dart"], all_tests)
        self.assertIn("lib/wrapper.dart", affected)
        self.assertIn("test/wrapper_test.dart", tests)

    def test_blocked_dart_parser(self):
        from tools.change_impact import engine
        original_script = engine.DART_SCRIPT
        engine.DART_SCRIPT = Path('/non/existent/script.dart')

        import sys
        from io import StringIO
        stdout = sys.stdout
        sys.stdout = StringIO()

        with self.assertRaises(SystemExit) as cm:
            engine.run_dart_parser("dummy.dart")

        output = sys.stdout.getvalue().strip()
        sys.stdout = stdout
        engine.DART_SCRIPT = original_script

        self.assertEqual(cm.exception.code, 1)
        self.assertTrue(output.startswith("BLOCKED:"))

if __name__ == '__main__':
    unittest.main()
