import ast
import json
import os
import shutil
import subprocess
from typing import Dict, List, Set, Any

class ChangeImpactEngine:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        if not os.access(repo_root, os.R_OK):
            raise PermissionError(f"Cannot read repository at {repo_root}")
        self._dart_executable = shutil.which('dart')

    def parse_python_ast(self, filepath: str) -> Dict[str, Any]:
        full_path = os.path.join(self.repo_root, filepath)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=filepath)

            imports = []
            exports = []
            has_dynamic = False

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        imports.append(name.name)
                elif isinstance(node, ast.ImportFrom):
                    level = node.level
                    if node.module:
                        imports.append(node.module)
                        for name in node.names:
                            imports.append(f"{node.module}.{name.name}")
                    else:
                        for name in node.names:
                            imports.append(f"{'.' * level}{name.name}")
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ('__import__', 'getattr', 'setattr', 'eval', 'exec'):
                            has_dynamic = True
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr == 'import_module':
                            has_dynamic = True

            return {
                'imports': list(set(imports)),
                'exports': exports,
                'has_dynamic': has_dynamic,
                'error': None
            }
        except SyntaxError as e:
            return {
                'imports': [],
                'exports': [],
                'has_dynamic': False,
                'error': f'SyntaxError: {str(e)}'
            }
        except Exception as e:
            return {
                'imports': [],
                'exports': [],
                'has_dynamic': False,
                'error': str(e)
            }

    def _parse_dart_files(self, filepaths: List[str]) -> Dict[str, Dict[str, Any]]:
        results = {fp: {'imports': [], 'exports': [], 'has_dynamic': False, 'error': None} for fp in filepaths}

        if not self._dart_executable:
            for fp in filepaths:
                results[fp]['error'] = 'BLOCKED: Dart parser not available'
            return results

        parser_bin = os.path.join(self.repo_root, 'tools', 'change_impact', 'dart_ast_parser', 'bin', 'parse.dart')
        if not os.path.exists(parser_bin):
            for fp in filepaths:
                results[fp]['error'] = 'BLOCKED: Dart parser not available'
            return results

        try:
            cwd = os.path.join(self.repo_root, 'tools', 'change_impact', 'dart_ast_parser')
            # Use json to pass multiple files to the dart script to avoid O(N) spawn overhead
            # We need to modify parse.dart to support a list of files
            # For this version, let's just make parse.dart accept a JSON list via stdin

            input_data = json.dumps([os.path.join(self.repo_root, fp) for fp in filepaths])

            result = subprocess.run(
                [self._dart_executable, 'run', 'bin/parse.dart'],
                cwd=cwd,
                input=input_data,
                capture_output=True,
                text=True,
                check=True
            )

            # The dart script outputs a JSON object mapping filepath to data
            out = result.stdout.strip()
            # find the JSON object line
            for line in reversed(out.split('\n')):
                try:
                    parsed = json.loads(line)
                    if isinstance(parsed, dict):
                        # Map back to relative paths
                        for abs_path, data in parsed.items():
                            rel = os.path.relpath(abs_path, self.repo_root)
                            if rel in results:
                                results[rel] = data
                        break
                except:
                    continue
            return results
        except subprocess.CalledProcessError as e:
            for fp in filepaths:
                results[fp]['error'] = f'Parser error: {e.stderr}'
            return results
        except Exception as e:
            for fp in filepaths:
                results[fp]['error'] = str(e)
            return results

    def extract_dependencies(self) -> Dict[str, Dict[str, Any]]:
        graph = {}
        dart_files = []
        for root, _, files in os.walk(self.repo_root):
            if '.git' in root or 'node_modules' in root:
                continue
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                if file.endswith('.py'):
                    graph[rel_path] = self.parse_python_ast(rel_path)
                elif file.endswith('.dart'):
                    dart_files.append(rel_path)

        if dart_files:
            dart_results = self._parse_dart_files(dart_files)
            graph.update(dart_results)

        return graph

    def get_reverse_dependencies(self, graph: Dict[str, Dict[str, Any]]) -> Dict[str, Set[str]]:
        rev_graph = {}
        for file, info in graph.items():
            if info.get('error'):
                continue

            all_deps = info.get('imports', []) + info.get('exports', [])
            for imp in all_deps:
                if imp not in rev_graph:
                    rev_graph[imp] = set()
                rev_graph[imp].add(file)

                # Dart package match logic handling package:
                if imp.startswith('package:'):
                    # For example package:my_repo/module.dart -> try to map to local if possible
                    # This requires knowledge of package name, we will just broadly track it
                    # by trimming package prefix and mapping it
                    parts = imp.replace('package:', '').split('/')
                    if len(parts) > 1:
                        target = '/'.join(parts[1:]) # rough heuristic for local package mapping
                        if target not in rev_graph:
                            rev_graph[target] = set()
                        rev_graph[target].add(file)
                elif imp.endswith('.dart') and file.endswith('.dart'):
                    dir_path = os.path.dirname(file)
                    target_path = os.path.normpath(os.path.join(dir_path, imp))
                    if target_path not in rev_graph:
                        rev_graph[target_path] = set()
                    rev_graph[target_path].add(file)

        return rev_graph

    def analyze_impact(self, changed_files: List[str]) -> Dict[str, Any]:
        has_dart = any(f.endswith('.dart') for f in changed_files)
        if has_dart and not self._dart_executable:
            return {'error': 'BLOCKED: Dart parser not available'}

        if has_dart:
            parser_bin = os.path.join(self.repo_root, 'tools', 'change_impact', 'dart_ast_parser', 'bin', 'parse.dart')
            if not os.path.exists(parser_bin):
                return {'error': 'BLOCKED: Dart parser not available'}

        graph = self.extract_dependencies()
        rev_graph = self.get_reverse_dependencies(graph)

        impacted_files = set(changed_files)
        impacted_tests = set()
        uncertain_files = set()

        queue = list(changed_files)
        visited = set(changed_files)

        while queue:
            current = queue.pop(0)
            current_basename = os.path.splitext(os.path.basename(current))[0]
            current_dirname = os.path.dirname(current)

            for dep, dependants in rev_graph.items():
                match = False
                if current == dep or current.replace('\\', '/') == dep.replace('\\', '/'):
                    match = True
                else:
                    # Python advanced resolution
                    dep_base = dep.split('.')[-1]
                    if current_basename == dep_base:
                        match = True
                    # handle __init__.py package references
                    if current_basename == '__init__':
                        pkg_name = os.path.basename(current_dirname)
                        if pkg_name == dep_base or pkg_name in dep.split('.'):
                            match = True
                    # handle relative python imports
                    if dep.startswith('.'):
                        match = True # overly broad but safe fallback for relative imports

                    # Handle dart heuristic
                    if current.endswith('.dart') and dep in current:
                        match = True

                if match:
                    for dependant in dependants:
                        if dependant not in visited:
                            visited.add(dependant)
                            impacted_files.add(dependant)
                            queue.append(dependant)

            if current in graph:
                info = graph[current]
                if info.get('has_dynamic'):
                    uncertain_files.add(current)
                if info.get('error'):
                    pass

        for file in impacted_files:
            test_file = self._find_test_for_file(file)
            if test_file and os.path.exists(os.path.join(self.repo_root, test_file)):
                impacted_tests.add(test_file)

        if uncertain_files:
            impacted_tests.add('ALL_TESTS')

        return {
            'impacted_files': sorted(list(impacted_files)),
            'impacted_tests': sorted(list(impacted_tests)),
            'uncertain_files': sorted(list(uncertain_files)),
            'error': None
        }

    def _find_test_for_file(self, file: str) -> str:
        dirname = os.path.dirname(file)
        basename = os.path.basename(file)
        if file.endswith('.py'):
            if basename.startswith('test_'):
                return file
            return os.path.join(dirname, f"test_{basename}")
        elif file.endswith('.dart'):
            if basename.endswith('_test.dart'):
                return file
            return os.path.join(dirname, f"{os.path.splitext(basename)[0]}_test.dart")
        return ""
