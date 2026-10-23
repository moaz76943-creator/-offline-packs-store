import unittest
import os
import json
from tools.change_impact.engine import get_impacted_tests_and_files, resolve_python_import, resolve_dart_import, parse_python

class TestEngine(unittest.TestCase):
    def setUp(self):
        os.environ['TESTING_CHANGE_IMPACT'] = '1'

    def tearDown(self):
        if 'TESTING_CHANGE_IMPACT' in os.environ:
            del os.environ['TESTING_CHANGE_IMPACT']

    def test_python_simple_import(self):
        all_files = ['a.py', 'b.py', 'test_b.py', 'c.py']
        import tools.change_impact.engine as eng
        original_read = eng.parse_python

        def mock_open(*args, **kwargs):
            import io
            return io.StringIO('')
        import builtins
        original_open = builtins.open
        builtins.open = mock_open
        def mock_parse(file_path, content):
            if file_path == 'b.py':
                return {'imports': ['a'], 'has_uncertainty': False, 'error': False}
            elif file_path == 'test_b.py':
                return {'imports': ['b'], 'has_uncertainty': False, 'error': False}
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        eng.parse_python = mock_parse
        try:
            res = eng.get_impacted_tests_and_files(['a.py'], all_files=all_files, root_dir='.')
            self.assertIn('b.py', res['impacted_files'])
            self.assertIn('test_b.py', res['impacted_tests'])
        finally:
            builtins.open = original_open
            eng.parse_python = original_read

    def test_dynamic_uncertainty_widen(self):
        all_files = ['a.py', 'b.py', 'test_b.py', 'test_c.py', 'c.py']
        import tools.change_impact.engine as eng
        original_read = eng.parse_python

        def mock_open(*args, **kwargs):
            import io
            return io.StringIO('')
        import builtins
        original_open = builtins.open
        builtins.open = mock_open
        def mock_parse(file_path, content):
            if file_path == 'b.py':
                return {'imports': [], 'has_uncertainty': True, 'error': False}
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        eng.parse_python = mock_parse
        try:
            res = eng.get_impacted_tests_and_files(['a.py'], all_files=all_files, root_dir='.')
            self.assertIn('test_b.py', res['impacted_tests'])
            self.assertIn('test_c.py', res['impacted_tests'])
        finally:
            builtins.open = original_open
            eng.parse_python = original_read

    def test_python_cyclic_import(self):
        all_files = ['a.py', 'b.py', 'c.py', 'test_a.py']
        import tools.change_impact.engine as eng
        original_read = eng.parse_python

        def mock_open(*args, **kwargs):
            import io
            return io.StringIO('')
        import builtins
        original_open = builtins.open
        builtins.open = mock_open
        def mock_parse(file_path, content):
            if file_path == 'a.py':
                return {'imports': ['b'], 'has_uncertainty': False, 'error': False}
            elif file_path == 'b.py':
                return {'imports': ['c'], 'has_uncertainty': False, 'error': False}
            elif file_path == 'c.py':
                return {'imports': ['a'], 'has_uncertainty': False, 'error': False}
            elif file_path == 'test_a.py':
                return {'imports': ['a'], 'has_uncertainty': False, 'error': False}
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        eng.parse_python = mock_parse
        try:
            res = eng.get_impacted_tests_and_files(['b.py'], all_files=all_files, root_dir='.')
            self.assertIn('a.py', res['impacted_files'])
            self.assertIn('c.py', res['impacted_files'])
            self.assertIn('test_a.py', res['impacted_tests'])
        finally:
            builtins.open = original_open
            eng.parse_python = original_read

    def test_parse_python_syntax_error(self):
        content = "invalid syntax(("
        res = parse_python("err.py", content)
        self.assertTrue(res['has_uncertainty'])
        self.assertTrue(res['error'])

    def test_parse_python_dynamic(self):
        content = "__import__('os')"
        res = parse_python("dyn.py", content)
        self.assertTrue(res['has_uncertainty'])

    def test_file_rename_simulation(self):
        # A rename is essentially a deletion and an addition.
        # But we only get "changed_files" (which for a rename includes the new name, and the old name is gone).
        all_files = ['new_name.py', 'b.py', 'test_new_name.py']
        import tools.change_impact.engine as eng
        original_read = eng.parse_python

        def mock_open(*args, **kwargs):
            import io
            return io.StringIO('')
        import builtins
        original_open = builtins.open
        builtins.open = mock_open
        def mock_parse(file_path, content):
            if file_path == 'new_name.py':
                return {'imports': ['b'], 'has_uncertainty': False, 'error': False}
            elif file_path == 'b.py':
                return {'imports': [], 'has_uncertainty': False, 'error': False}
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        eng.parse_python = mock_parse
        try:
            res = eng.get_impacted_tests_and_files(['new_name.py'], all_files=all_files, root_dir='.')
            self.assertIn('new_name.py', res['impacted_files'])
            self.assertIn('test_new_name.py', res['impacted_tests'])
        finally:
            builtins.open = original_open
            eng.parse_python = original_read

    def test_python_import_from_submodule(self):
        all_files = ['pkg/__init__.py', 'pkg/sub.py', 'main.py']
        import tools.change_impact.engine as eng
        original_read = eng.parse_python

        def mock_open(*args, **kwargs):
            import io
            return io.StringIO('')
        import builtins
        original_open = builtins.open
        builtins.open = mock_open
        def mock_parse(file_path, content):
            if file_path == 'main.py':
                return eng.parse_python(file_path, "from pkg import sub\n")
            return {'imports': [], 'has_uncertainty': False, 'error': False}

        eng.parse_python = mock_parse
        try:
            res = eng.get_impacted_tests_and_files(['pkg/sub.py'], all_files=all_files, root_dir='.')
            self.assertIn('main.py', res['impacted_files'])
        finally:
            builtins.open = original_open
            eng.parse_python = original_read

if __name__ == '__main__':
    unittest.main()
