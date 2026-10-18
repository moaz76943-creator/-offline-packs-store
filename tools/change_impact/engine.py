import ast
import os
import subprocess
import sys
import json
from typing import Dict, List, Set, Tuple, Optional

class ChangeImpactEngine:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        self.dependency_graph: Dict[str, Set[str]] = {}
        self.reverse_dependency_graph: Dict[str, Set[str]] = {}
        self.dynamic_imports: Set[str] = set()

    def _resolve_python_import(self, module_name: str, base_path: str) -> Optional[str]:
        """Resolves a Python module name to a relative file path."""
        parts = module_name.split('.')
        # Try as a file
        file_path = os.path.join(*parts) + '.py'
        full_file_path = os.path.join(self.repo_root, file_path)
        if os.path.exists(full_file_path):
            return file_path

        # Try as a directory with __init__.py
        dir_path = os.path.join(*parts, '__init__.py')
        full_dir_path = os.path.join(self.repo_root, dir_path)
        if os.path.exists(full_dir_path):
            return dir_path

        # Try relative to base_path
        base_dir = os.path.dirname(os.path.join(self.repo_root, base_path))
        for p in [file_path, dir_path]:
            full_p = os.path.join(base_dir, p)
            if os.path.exists(full_p):
                return os.path.relpath(full_p, self.repo_root)

        return None

    def _resolve_dart_import(self, uri: str, base_path: str) -> Optional[str]:
        """Resolves a Dart import URI to a relative file path."""
        if uri.startswith('dart:'):
            return None
        if uri.startswith('package:'):
            return None

        # Relative path
        base_dir = os.path.dirname(os.path.join(self.repo_root, base_path))
        full_path = os.path.normpath(os.path.join(base_dir, uri))

        if full_path.startswith(self.repo_root):
            rel_path = os.path.relpath(full_path, self.repo_root)
            if os.path.exists(full_path):
                return rel_path
        return None

    def parse_python(self, file_path: str) -> Tuple[Set[str], bool]:
        deps = set()
        has_dynamic = False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        deps.add(name.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        deps.add(node.module)
                        # Also add individual names if they map to files
                        for name in node.names:
                            deps.add(f"{node.module}.{name.name}")
                    else:
                        # Handle relative imports without module name (e.g. from . import X)
                        for name in node.names:
                            deps.add(name.name)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                        has_dynamic = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                        has_dynamic = True
                    elif isinstance(node.func, ast.Name) and node.func.id == 'getattr':
                         has_dynamic = True
        except SyntaxError:
            pass
        return deps, has_dynamic

    def parse_dart(self, file_path: str) -> Tuple[Set[str], bool]:
        deps = set()
        has_dynamic = False
        try:
            # Use abspath relative to this file
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dart_parser_dir = os.path.join(script_dir, 'dart_parser')
            parser_path = os.path.join(dart_parser_dir, 'bin', 'dart_parser.dart')

            env = os.environ.copy()

            # Auto-run dart pub get if dependencies are not resolved
            if not os.path.exists(os.path.join(dart_parser_dir, '.dart_tool', 'package_config.json')):
                subprocess.run(['dart', 'pub', 'get'], capture_output=True, check=True, cwd=dart_parser_dir, env=env)

            # Ensure dart parser can run
            result = subprocess.run(['dart', 'run', parser_path, file_path], capture_output=True, text=True, check=True, cwd=dart_parser_dir, env=env)
            for line in result.stdout.splitlines():
                if line.startswith('DEPS:'):
                    raw_deps = line[5:].split(',')
                    for dep in raw_deps:
                        if dep:
                            deps.add(dep)
        except subprocess.CalledProcessError:
            # If dart parser fails, assume dynamic/unknown and report missing capability
            print('BLOCKED: Missing or failing dart parser capability')
            has_dynamic = True
        except FileNotFoundError:
            print('BLOCKED: Missing dart parser capability')
            has_dynamic = True

        return deps, has_dynamic

    def analyze(self):
        for root, dirs, files in os.walk(self.repo_root):
            # Skip hidden and some dirs
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('dart_parser', '__pycache__')]

            for file in files:
                if not (file.endswith('.py') or file.endswith('.dart')):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.repo_root)

                raw_deps = set()
                resolved_deps = set()
                is_dynamic = False

                if file.endswith('.py'):
                    raw_deps, is_dynamic = self.parse_python(full_path)
                    for dep in raw_deps:
                        resolved = self._resolve_python_import(dep, rel_path)
                        if resolved:
                            resolved_deps.add(resolved)
                elif file.endswith('.dart'):
                    raw_deps, is_dynamic = self.parse_dart(full_path)
                    for dep in raw_deps:
                        resolved = self._resolve_dart_import(dep, rel_path)
                        if resolved:
                            resolved_deps.add(resolved)

                if is_dynamic:
                    self.dynamic_imports.add(rel_path)

                self.dependency_graph[rel_path] = resolved_deps
                for dep in resolved_deps:
                    self.reverse_dependency_graph.setdefault(dep, set()).add(rel_path)

    def get_impacted_tests(self, changed_files: List[str]) -> Tuple[Set[str], Set[str]]:
        impacted_files = set(changed_files)
        queue = list(changed_files)

        while queue:
            current = queue.pop(0)
            for file in self.reverse_dependency_graph.get(current, set()):
                if file not in impacted_files:
                    impacted_files.add(file)
                    queue.append(file)

        # Find impacted tests
        tests = set()
        all_tests = set(f for f in self.dependency_graph.keys() if 'test' in f.lower())

        for file in impacted_files:
            if file in all_tests:
                tests.add(file)

        # Widen scope if dynamic imports are involved
        # A true missing link means an unmapped file might be the target of a dynamic import.
        # If there are ANY dynamic imports in the codebase, and an explicitly changed file
        # is unmapped (i.e., no dependents were found), we MUST widen the scope.
        # To be safe, if there's any dynamic loading anywhere in the project, we widen on any change.
        if self.dynamic_imports:
            # We don't know what might be dynamically imported, so we must run all tests
            tests = all_tests

        return impacted_files, tests
