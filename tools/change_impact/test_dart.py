import unittest
import os
import tempfile
import shutil
import json
from tools.change_impact.engine import run_dart_parser, get_impacted_tests_and_files

class TestDartParser(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        os.environ['TESTING_CHANGE_IMPACT'] = '1'

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        if 'TESTING_CHANGE_IMPACT' in os.environ:
            del os.environ['TESTING_CHANGE_IMPACT']

    def test_run_dart_parser(self):
        with open('ok.dart', 'w') as f:
            f.write("import 'dart:io';")

        with open('err.dart', 'w') as f:
            f.write("invalid dart code")

        with open('dyn.dart', 'w') as f:
            f.write("import 'dart:mirrors';")

        res = run_dart_parser(['ok.dart', 'err.dart', 'dyn.dart'])

        self.assertFalse(res['ok.dart']['has_uncertainty'])
        self.assertFalse(res['ok.dart']['error'])
        self.assertIn('dart:io', res['ok.dart']['imports'])

        self.assertTrue(res['err.dart']['error'])

        self.assertTrue(res['dyn.dart']['has_uncertainty'])

    def test_mixed_resolution(self):
        all_files = ['main.py', 'helper.dart', 'helper_test.dart', 'test_main.py']

        import tools.change_impact.engine as eng
        original_read = eng.parse_python
        original_run_dart = eng.run_dart_parser

        def mock_parse(file_path, content):
            if file_path == 'test_main.py':
                return {'imports': ['main'], 'has_uncertainty': False, 'error': False}
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        def mock_run_dart(paths):
            res = {}
            for p in paths:
                if p == 'helper_test.dart':
                    res[p] = {'imports': ['helper.dart'], 'has_uncertainty': False, 'error': False}
                else:
                    res[p] = {'imports': [], 'has_uncertainty': False, 'error': False}
            return res

        eng.parse_python = mock_parse
        eng.run_dart_parser = mock_run_dart

        try:
            res = eng.get_impacted_tests_and_files(['helper.dart'], all_files=all_files, root_dir='.')
            self.assertIn('helper.dart', res['impacted_files'])
            self.assertIn('helper_test.dart', res['impacted_tests'])

            res2 = eng.get_impacted_tests_and_files(['main.py'], all_files=all_files, root_dir='.')
            self.assertIn('main.py', res2['impacted_files'])
            self.assertIn('test_main.py', res2['impacted_tests'])
        finally:
            eng.parse_python = original_read
            eng.run_dart_parser = original_run_dart

if __name__ == '__main__':
    unittest.main()
