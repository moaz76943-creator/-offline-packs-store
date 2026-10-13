import unittest
import tempfile
import os
from pathlib import Path
from tools.change_impact.engine import ChangeImpactEngine

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        # We need a dummy Dart parser for testing because we can't reliably invoke dart in the test suite
        # without ensuring the dart environment is fully isolated or mocked.
        # Actually, since Dart is available, we can just write real files and test the Python parsing first,
        # then mock Dart if needed, but since Dart is available we can write real Dart parser integration.

        # But wait, our engine invokes dart_parser which is in the actual source tree.
        # Let's set up the test engine to point its root to the actual repo root for the dart parser
        # and test files in temp_dir.
        pass

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_file(self, path: str, content: str):
        full_path = self.root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')

    def _create_engine(self):
        engine = ChangeImpactEngine(str(self.root))
        # Override the dart parser path to point to the real one in the repo
        engine.dart_parser_path = Path.cwd() / 'tools' / 'change_impact' / 'dart_parser' / 'bin' / 'parse.dart'
        return engine

    def test_direct_imports(self):
        self._write_file('a.py', 'def foo(): pass')
        self._write_file('b.py', 'import a')
        self._write_file('test_b.py', 'import b')

        engine = self._create_engine()
        engine.build_graph()
        result = engine.analyze_impact(['a.py'])

        self.assertFalse(result['uncertain'])
        self.assertIn('a.py', result['affected_files'])
        self.assertIn('b.py', result['affected_files'])
        self.assertIn('test_b.py', result['affected_files'])
        self.assertEqual(result['impacted_tests'], ['test_b.py'])

    def test_cyclic_imports(self):
        self._write_file('c1.py', 'import c2')
        self._write_file('c2.py', 'import c1\nimport c3')
        self._write_file('c3.py', 'import c1')
        self._write_file('test_c.py', 'import c1')

        engine = self._create_engine()
        engine.build_graph()
        result = engine.analyze_impact(['c2.py'])

        self.assertIn('c1.py', result['affected_files'])
        self.assertIn('c2.py', result['affected_files'])
        self.assertIn('c3.py', result['affected_files'])
        self.assertEqual(result['impacted_tests'], ['test_c.py'])

    def test_renames(self):
        # test `import as` and `from import`
        self._write_file('mod.py', 'x = 1')
        self._write_file('consumer.py', 'from mod import x as y')
        self._write_file('test_consumer.py', 'import consumer')

        engine = self._create_engine()
        engine.build_graph()
        result = engine.analyze_impact(['mod.py'])

        self.assertIn('consumer.py', result['affected_files'])
        self.assertIn('test_consumer.py', result['impacted_tests'])

    def test_indirect_imports(self):
        self._write_file('pkg/__init__.py', '')
        self._write_file('pkg/core.py', 'def core(): pass')
        self._write_file('pkg/api.py', 'from .core import core')
        self._write_file('app.py', 'from pkg.api import core')
        self._write_file('test_app.py', 'import app')

        engine = self._create_engine()
        engine.build_graph()
        result = engine.analyze_impact(['pkg/core.py'])

        self.assertIn('pkg/api.py', result['affected_files'])
        self.assertIn('app.py', result['affected_files'])
        self.assertEqual(result['impacted_tests'], ['test_app.py'])

    def test_syntax_errors(self):
        self._write_file('good.py', 'x = 1')
        self._write_file('bad.py', 'x = 1\nthis is a syntax error!')
        self._write_file('test_good.py', 'import good')

        engine = self._create_engine()
        engine.build_graph()
        result = engine.analyze_impact(['good.py'])

        self.assertIn('good.py', result['affected_files'])
        self.assertEqual(result['impacted_tests'], ['test_good.py'])
        # The bad file shouldn't crash the engine, just fail to parse imports.

    def test_mixed_source_trees(self):
        # Setup Dart files
        self._write_file('lib/core.dart', 'class Core {}')
        self._write_file('lib/app.dart', "import 'core.dart';\nclass App {}")
        self._write_file('test/app_test.dart', "import '../lib/app.dart';\nvoid main() {}")

        # Setup Python files
        self._write_file('scripts/tool.py', 'def run(): pass')
        self._write_file('scripts/test_tool.py', 'import tool')

        engine = self._create_engine()
        engine.build_graph()

        # Test Dart impact
        dart_result = engine.analyze_impact(['lib/core.dart'])
        self.assertIn('lib/app.dart', dart_result['affected_files'])
        self.assertEqual(dart_result['impacted_tests'], ['test/app_test.dart'])

        # Test Python impact doesn't leak into Dart (no edges between them)
        py_result = engine.analyze_impact(['scripts/tool.py'])
        self.assertEqual(py_result['impacted_tests'], ['scripts/test_tool.py'])

    def test_dynamic_import_uncertainty(self):
        self._write_file('main.py', 'def run():\n  m = __import__("dynamic_plugin")')
        self._write_file('dynamic_plugin.py', 'print("plugin")')
        self._write_file('test_main.py', 'import main')
        self._write_file('test_plugin.py', 'import dynamic_plugin')
        self._write_file('test_unrelated.py', 'pass') # just a test file

        engine = self._create_engine()
        engine.build_graph()

        # When main.py is changed, it contains a dynamic import, triggering uncertainty.
        # This should widen impacted_tests to all test files.
        result = engine.analyze_impact(['main.py'])

        self.assertTrue(result['uncertain'])

        # Since it's uncertain, all known test files should be returned
        self.assertIn('test_main.py', result['impacted_tests'])
        self.assertIn('test_plugin.py', result['impacted_tests'])
        self.assertIn('test_unrelated.py', result['impacted_tests'])
