import ast
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple

class DependencyEngine:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        if not os.access(self.repo_root, os.R_OK):
            raise PermissionError(f"Cannot read repository root: {self.repo_root}")

        # Parser is located relative to this file, not necessarily the analyzed repo root
        self.dart_parser_dir = Path(__file__).resolve().parent / 'dart_parser'
        self.dart_parser_path = self.dart_parser_dir / 'bin' / 'dart_parser'

        # Ensure dart parser exists and is executable
        if not self.dart_parser_path.exists():
             self._build_dart_parser()

    def _build_dart_parser(self):
        if not self.dart_parser_dir.exists():
            raise FileNotFoundError(f"Dart parser source not found at {self.dart_parser_dir}")

        try:
            # Explicitly run pub get first as missing it can cause compile failures in clean environments
            subprocess.run(
                ['dart', 'pub', 'get'],
                cwd=str(self.dart_parser_dir),
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['dart', 'compile', 'exe', 'bin/dart_parser.dart', '-o', 'bin/dart_parser'],
                cwd=str(self.dart_parser_dir),
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to compile Dart parser: {e.stderr.decode()}")

    def _resolve_python_import(self, module: str, current_file: Path) -> str:
        """Attempts to resolve a Python module name to a file path within the repo."""
        if not module:
            return None

        parts = module.split('.')

        # Try relative to repo root
        path = self.repo_root.joinpath(*parts)
        if path.with_suffix('.py').exists():
            return str(path.with_suffix('.py').relative_to(self.repo_root))
        if path.is_dir() and (path / '__init__.py').exists():
            return str((path / '__init__.py').relative_to(self.repo_root))

        # Try relative to current file's directory
        path = current_file.parent.joinpath(*parts)
        if path.with_suffix('.py').exists():
            return str(path.with_suffix('.py').relative_to(self.repo_root))
        if path.is_dir() and (path / '__init__.py').exists():
             return str((path / '__init__.py').relative_to(self.repo_root))

        return module

    def analyze_python(self, file_path: Path) -> Tuple[Set[str], bool]:
        """Analyzes a Python file for dependencies and dynamic imports."""
        try:
            content = file_path.read_text()
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            return set(), True # Widen scope on error

        deps = set()
        has_dynamic = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    resolved = self._resolve_python_import(name.name, file_path)
                    if resolved:
                        deps.add(resolved)
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, 'module', None):
                    module = node.module
                    if node.level > 0:
                        # Handle relative imports without lstrip('.') destruction
                        module_parts = list(file_path.relative_to(self.repo_root).parent.parts)
                        # Go up for each level > 1
                        for _ in range(node.level - 1):
                            if module_parts:
                                module_parts.pop()
                        base = '.'.join(module_parts)
                        if base:
                            module = f"{base}.{module}"

                    # For `from A.B import C`, check if C is a module or an object
                    for name in node.names:
                        full_module = f"{module}.{name.name}"
                        resolved = self._resolve_python_import(full_module, file_path)
                        if resolved and resolved != full_module:
                            # It resolved to a file
                            deps.add(resolved)
                        else:
                            # Try just the module part
                            resolved_mod = self._resolve_python_import(module, file_path)
                            if resolved_mod:
                                deps.add(resolved_mod)
                else:
                    # from . import A
                    if node.level > 0:
                        module_parts = list(file_path.relative_to(self.repo_root).parent.parts)
                        for _ in range(node.level - 1):
                            if module_parts:
                                module_parts.pop()
                        base = '.'.join(module_parts)
                        for name in node.names:
                            if base:
                                resolved = self._resolve_python_import(f"{base}.{name.name}", file_path)
                            else:
                                resolved = self._resolve_python_import(name.name, file_path)
                            if resolved:
                                deps.add(resolved)

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    has_dynamic = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                    has_dynamic = True

        return deps, has_dynamic

    def analyze_dart(self, file_path: Path) -> Tuple[Set[str], bool]:
        """Analyzes a Dart file for dependencies and dynamic imports using the external parser."""
        try:
            result = subprocess.run(
                [str(self.dart_parser_path), str(file_path)],
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            if 'error' in data:
                return set(), True

            deps = set()
            for dep in data.get('dependencies', []):
                # Try to resolve relative paths
                if not dep.startswith('dart:') and not dep.startswith('package:'):
                    dep_path = (file_path.parent / dep).resolve()
                    if str(dep_path).startswith(str(self.repo_root)):
                        deps.add(str(dep_path.relative_to(self.repo_root)))
                    else:
                        deps.add(dep)
                else:
                     deps.add(dep)

            return deps, data.get('dynamic', False)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return set(), True

    def build_graph(self, files: List[Path]) -> Dict[str, Dict[str, any]]:
        """Builds a directed dependency graph for the given files."""
        graph = {}
        for file_path in files:
            if not file_path.exists():
                continue

            deps = set()
            has_dynamic = False

            if file_path.suffix == '.py':
                deps, has_dynamic = self.analyze_python(file_path)
            elif file_path.suffix == '.dart':
                deps, has_dynamic = self.analyze_dart(file_path)

            graph[str(file_path.relative_to(self.repo_root))] = {
                'dependencies': sorted(list(deps)),
                'dynamic': has_dynamic
            }

        return graph

    def determine_impact(self, changed_files: List[str], graph: Dict[str, Dict[str, any]]) -> Dict[str, any]:
        """Determines impacted files and corresponding tests based on changes and the dependency graph."""
        impacted_files = set(changed_files)
        uncertain = False

        # Build reverse graph
        reverse_graph = {}
        for file, data in graph.items():
            if data['dynamic']:
                uncertain = True
            for dep in data['dependencies']:
                if dep not in reverse_graph:
                    reverse_graph[dep] = set()
                reverse_graph[dep].add(file)

        # Traverse reverse graph from changed files
        queue = list(changed_files)
        while queue:
            current = queue.pop(0)
            if current in reverse_graph:
                for dependent in reverse_graph[current]:
                    if dependent not in impacted_files:
                        impacted_files.add(dependent)
                        queue.append(dependent)

        # Map impacted files to test IDs based on naming conventions
        test_ids = set()
        for file in impacted_files:
            file_path = Path(file)
            # Python test convention
            if file_path.name.startswith('test_') and file_path.suffix == '.py':
                test_ids.add(file)
            elif file_path.suffix == '.py':
                potential_test = file_path.parent / f"test_{file_path.name}"
                if str(potential_test) in graph:
                    test_ids.add(str(potential_test))
            # Dart test convention
            elif file_path.name.endswith('_test.dart'):
                test_ids.add(file)
            elif file_path.suffix == '.dart':
                potential_test = file_path.parent / f"{file_path.stem}_test.dart"
                if str(potential_test) in graph:
                    test_ids.add(str(potential_test))

        return {
            'impacted_files': sorted(list(impacted_files)),
            'test_ids': sorted(list(test_ids)),
            'uncertain': uncertain
        }
