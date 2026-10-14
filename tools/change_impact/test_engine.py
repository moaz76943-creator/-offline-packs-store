import unittest
import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from engine import ChangeImpactEngine, analyze_changes

class TestChangeImpactEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ChangeImpactEngine(repo_root=os.getcwd())

    def test_dynamic_python(self):
        self.engine.parse_python_file('tools/change_impact/test_data/python_test_basic.py')
        self.assertIn('tools/change_impact/test_data/python_test_basic.py', self.engine.dynamic_files)

    def test_dynamic_dart(self):
        self.engine.parse_dart_file('tools/change_impact/test_data/dart_test_basic.dart')
        self.assertIn('tools/change_impact/test_data/dart_test_basic.dart', self.engine.dynamic_files)

    def test_missing_dart_parser(self):
        old_path = self.engine.dart_parser_script
        self.engine.dart_parser_script = '/does/not/exist'
        self.engine.dart_blocked = True

        with self.assertRaises(RuntimeError) as context:
            self.engine.parse_dart_file('tools/change_impact/test_data/dart_test_basic.dart')

        self.assertTrue('BLOCKED' in str(context.exception))

        self.engine.dart_parser_script = old_path
        self.engine.dart_blocked = False

    def test_analyze_changes(self):
        res = analyze_changes(os.getcwd(), ['tools/change_impact/test_data/python_test_basic.py'])
        self.assertEqual(res['status'], 'OK')
        self.assertTrue(res['widen'])

    def test_cyclic_imports(self):
        with open('tools/change_impact/test_data/cycle1.py', 'w') as f:
            f.write('import tools.change_impact.test_data.cycle2\n')
        with open('tools/change_impact/test_data/cycle2.py', 'w') as f:
            f.write('import tools.change_impact.test_data.cycle1\n')

        self.engine.scan_project()
        impacted, _ = self.engine.get_impacted_files(['tools/change_impact/test_data/cycle1.py'])
        self.assertIn('tools/change_impact/test_data/cycle2.py', impacted)

    def test_syntax_error(self):
        err_path = 'tools/change_impact/test_data/tmp_err.py'
        with open(err_path, 'w') as f:
            f.write('import def print\n')

        self.engine.parse_python_file(err_path)
        os.remove(err_path)

    def test_renames(self):
        self.engine.scan_project()
        impacted, _ = self.engine.get_impacted_files(['tools/change_impact/test_data/rename2.py'])
        self.assertIn('tools/change_impact/test_data/rename1.py', impacted)

    def test_mixed_source_trees(self):
        self.engine.scan_project()
        impacted_py, _ = self.engine.get_impacted_files(['tools/change_impact/test_data/mixed_helper.py'])
        self.assertIn('tools/change_impact/test_data/mixed_python.py', impacted_py)

        impacted_dart, _ = self.engine.get_impacted_files(['tools/change_impact/test_data/mixed_helper.dart'])
        self.assertIn('tools/change_impact/test_data/mixed_dart.dart', impacted_dart)

    def test_indirect_imports(self):
        with open('tools/change_impact/test_data/ind1.py', 'w') as f:
            f.write('import tools.change_impact.test_data.ind2\n')
        with open('tools/change_impact/test_data/ind2.py', 'w') as f:
            f.write('import tools.change_impact.test_data.ind3\n')
        with open('tools/change_impact/test_data/ind3.py', 'w') as f:
            f.write('def foo(): pass\n')

        self.engine.scan_project()
        impacted, _ = self.engine.get_impacted_files(['tools/change_impact/test_data/ind3.py'])
        self.assertIn('tools/change_impact/test_data/ind2.py', impacted)
        self.assertIn('tools/change_impact/test_data/ind1.py', impacted)

if __name__ == '__main__':
    unittest.main()
