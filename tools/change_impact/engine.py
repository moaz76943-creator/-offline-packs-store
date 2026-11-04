import sys
import ast
import json
import subprocess
import os
import tempfile
from collections import defaultdict

def check_repository_access(root_dir='.'):
    # In tests, we create temporary directories that are not git repos
    # We should only check if we are actually checking real directories
    if 'TESTING_CHANGE_IMPACT' in os.environ:
        return

    try:
        subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=root_dir, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("BLOCKED")
        sys.exit(1)

def parse_python(file_path, content):
    imports = []
    has_uncertainty = False
    error = False
    try:
        tree = ast.parse(content, filename=file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = node.level

                for alias in node.names:
                    if level > 0:
                        prefix = "." * level
                        if module:
                            imports.append(f"{prefix}{module}.{alias.name}")
                            imports.append(f"{prefix}{module}")
                        else:
                            imports.append(f"{prefix}{alias.name}")
                    else:
                        if module:
                            imports.append(f"{module}.{alias.name}")
                            imports.append(module)
                        else:
                            imports.append(alias.name)

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ('__import__', 'eval', 'exec', 'getattr', 'hasattr'):
                        has_uncertainty = True
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in ('__import__', 'eval', 'exec'):
                        has_uncertainty = True
    except SyntaxError:
        error = True
        has_uncertainty = True
    except Exception:
        error = True
        has_uncertainty = True

    return {
        "imports": imports,
        "has_uncertainty": has_uncertainty,
        "error": error
    }

def resolve_python_import(file_path, imp_str, all_files):
    resolved = set()

    if imp_str.startswith('.'):
        level = len(imp_str) - len(imp_str.lstrip('.'))
        rest = imp_str.lstrip('.')
        parts = file_path.split('/')
        if level <= len(parts):
            base = parts[:-level]
            if rest:
                target = '/'.join(base + rest.split('.')) + '.py'
            else:
                target = '/'.join(base) + '.py'
            if target in all_files:
                resolved.add(target)
            init_target = target[:-3] + '/__init__.py'
            if init_target in all_files:
                resolved.add(init_target)
    else:
        target_path = '/'.join(imp_str.split('.')) + '.py'
        if target_path in all_files:
            resolved.add(target_path)

        target_init = '/'.join(imp_str.split('.')) + '/__init__.py'
        if target_init in all_files:
            resolved.add(target_init)

    return list(resolved)

def run_dart_parser(dart_files):
    if not dart_files:
        return {}
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.json') as f:
        json.dump(dart_files, f)
        temp_path = f.name

    try:
        dart_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dart_parser.dart')
        tool_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.exists(os.path.join(tool_dir, 'pubspec.yaml')) and not os.path.exists(os.path.join(tool_dir, '.dart_tool')):
            pub_result = subprocess.run(['dart', 'pub', 'get'], cwd=tool_dir, capture_output=True, text=True)
            if pub_result.returncode != 0:
                print("BLOCKED")
                sys.exit(1)

        result = subprocess.run(['dart', dart_script, temp_path], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except FileNotFoundError:
        print("BLOCKED")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print("BLOCKED")
        sys.exit(1)
    except Exception as e:
        print("BLOCKED")
        sys.exit(1)
    finally:
        os.unlink(temp_path)

def resolve_dart_import(file_path, imp_str, all_files):
    if imp_str.startswith('dart:'):
        return []
    elif imp_str.startswith('package:'):
        parts = imp_str[len('package:'):].split('/')
        if len(parts) > 1:
            rest = '/'.join(parts[1:])
            possible_path = f"lib/{rest}"
            if possible_path in all_files:
                return [possible_path]
            if rest in all_files:
                return [rest]
        return []
    else:
        base = os.path.dirname(file_path)
        if base == '':
            target = imp_str
        else:
            target = os.path.normpath(os.path.join(base, imp_str)).replace('\\', '/')
        if target in all_files:
            return [target]
    return []

def scan_files(root_dir):
    all_files = set()
    for root, dirs, files in os.walk(root_dir):
        # Exclude directories
        if '.git' in dirs:
            dirs.remove('.git')
        if '.dart_tool' in dirs:
            dirs.remove('.dart_tool')

        for f in files:
            if f.endswith('.py') or f.endswith('.dart'):
                path = os.path.relpath(os.path.join(root, f), root_dir)
                path = path.replace('\\', '/')
                all_files.add(path)
    return list(all_files)

def get_impacted_tests_and_files(changed_files, all_files=None, root_dir='.'):
    check_repository_access(root_dir)

    if all_files is None:
        all_files = scan_files(root_dir)

    all_files_set = set(all_files)

    py_files = [f for f in all_files if f.endswith('.py')]
    dart_files = [f for f in all_files if f.endswith('.dart')]

    file_info = {}
    for f in py_files:
        path = os.path.join(root_dir, f)
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            file_info[f] = parse_python(f, content)
        except Exception:
            file_info[f] = {"imports": [], "has_uncertainty": True, "error": True}

    if dart_files:
        dart_results = run_dart_parser([os.path.join(root_dir, f) for f in dart_files])
        for f in dart_files:
            key = os.path.join(root_dir, f)
            info = dart_results.get(key, {"imports": [], "has_uncertainty": True, "error": True})
            file_info[f] = info

    forward_graph = defaultdict(list)
    uncertain_files = set()

    for f, info in file_info.items():
        if info['has_uncertainty'] or info['error']:
            uncertain_files.add(f)

        for imp in info['imports']:
            if f.endswith('.py'):
                resolved = resolve_python_import(f, imp, all_files_set)
            else:
                resolved = resolve_dart_import(f, imp, all_files_set)
            forward_graph[f].extend(resolved)

    rev_graph = defaultdict(list)
    for f, deps in forward_graph.items():
        for dep in deps:
            rev_graph[dep].append(f)

    impacted_files = set(changed_files)
    queue = list(changed_files)

    if changed_files:
        for uf in uncertain_files:
            if uf not in impacted_files:
                impacted_files.add(uf)
                queue.append(uf)

    while queue:
        curr = queue.pop(0)
        for dependant in rev_graph.get(curr, []):
            if dependant not in impacted_files:
                impacted_files.add(dependant)
                queue.append(dependant)

    impacted_tests = set()
    for f in impacted_files:
        if ('test_' in f or f.endswith('_test.dart') or '/test/' in f or '/tests/' in f):
            impacted_tests.add(f)
        else:
            if f.endswith('.py'):
                dirname, basename = os.path.split(f)
                guess1 = os.path.join(dirname, f"test_{basename}").replace('\\', '/')
                guess2 = os.path.join("tests", dirname, f"test_{basename}").replace('\\', '/')
                if guess1 in all_files_set:
                    impacted_tests.add(guess1)
                if guess2 in all_files_set:
                    impacted_tests.add(guess2)
            elif f.endswith('.dart'):
                dirname, basename = os.path.split(f)
                name = basename[:-5]
                guess1 = os.path.join(dirname, f"{name}_test.dart").replace('\\', '/')
                guess2 = os.path.join("test", dirname, f"{name}_test.dart").replace('\\', '/')
                if guess1 in all_files_set:
                    impacted_tests.add(guess1)
                if guess2 in all_files_set:
                    impacted_tests.add(guess2)

    if uncertain_files and changed_files:
        for f in all_files:
            if ('test_' in f or f.endswith('_test.dart') or '/test/' in f or '/tests/' in f):
                impacted_tests.add(f)

    return {
        "impacted_files": sorted(list(impacted_files)),
        "impacted_tests": sorted(list(impacted_tests))
    }

def main(changed_files=None):
    if changed_files is None:
        changed_files = sys.argv[1:]

    result = get_impacted_tests_and_files(changed_files)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
