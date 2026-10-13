import os
from pathlib import Path
import json
import subprocess
from collections import defaultdict
from tools.change_impact.python_parser import parse_python_file

class ChangeImpactEngine:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.dart_parser_path = self.root_dir / 'tools' / 'change_impact' / 'dart_parser' / 'bin' / 'parse.dart'
        self.files = set()

        # Mapping from a module string to the file paths that define it
        self.module_to_files = defaultdict(list)

        # Directed graph: file_path -> list of file_paths that depend on it
        # (i.e. edges point in the direction of impact: from dependency to dependent)
        self.reverse_deps = defaultdict(set)

        # Files that contain uncertain elements (dynamic imports, reflection)
        self.uncertain_files = set()

        # Test files identified by pattern
        self.test_files = set()

    def _find_source_files(self):
        """Recursively yield all .py and .dart files in root directory."""
        for path in self.root_dir.rglob('*'):
            if path.is_file():
                if path.suffix in ('.py', '.dart'):
                    # Skip files in common build/hidden directories
                    parts = path.parts
                    if any(p.startswith('.') or p in ('__pycache__', 'build', 'dart_parser') for p in parts):
                        # Note: we skip dart_parser since it's an internal tool for this task,
                        # but we can configure this if needed.
                        if 'dart_parser' in parts and 'tools' in parts and 'change_impact' in parts:
                            continue
                        if not ('dart_parser' in parts and 'tools' in parts and 'change_impact' in parts):
                            if any(p.startswith('.') and p != '.' for p in parts):
                                continue
                            if '__pycache__' in parts or 'build' in parts:
                                continue

                    self.files.add(path)

                    # Check if it's a test file based on naming conventions
                    name = path.name
                    if path.suffix == '.py' and name.startswith('test_'):
                        self.test_files.add(path)
                    elif path.suffix == '.dart' and name.endswith('_test.dart'):
                        self.test_files.add(path)

    def _run_dart_parser(self, filepath: Path) -> dict:
        try:
            # Run dart parser from its own directory so it picks up its pubspec dependencies
            dart_cwd = self.dart_parser_path.parent.parent
            result = subprocess.run(
                ['dart', 'run', 'bin/parse.dart', str(filepath)],
                capture_output=True, text=True, check=True, cwd=str(dart_cwd)
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            # We can't parse it, maybe a syntax error or a mixed up file.
            return {'imports': [], 'exports': [], 'has_reflection': False, 'error': e.stderr}
        except json.JSONDecodeError:
            return {'imports': [], 'exports': [], 'has_reflection': False, 'error': 'Invalid JSON from parser'}
        except FileNotFoundError:
            raise RuntimeError("BLOCKED: Missing parser capability (dart not found)")

    def _resolve_python_import(self, imp: str, base_path: Path):
        # Convert an import like 'a.b.c' to possible file paths 'a/b/c.py' or 'a/b/c/__init__.py'
        # Or if it's a relative import like '.a' or '..a' or '.a.b', it's already converted to 'pkg.a' by python_parser.py
        # Actually python_parser converts 'from . import core' inside 'pkg.api' to 'pkg.core'
        # if node.module is not empty. Wait, if it's top level, the prefix might be just '.core'

        parts = imp.split('.')
        path_str = os.path.join(*parts)

        # If it's a relative path prefix like '..subpackage'
        if imp.startswith('.'):
            # We need to resolve relative to base_path
            dot_count = len(imp) - len(imp.lstrip('.'))
            name_parts = imp.lstrip('.').split('.') if imp.lstrip('.') else []

            # Start from the base_path's parent
            current_dir = base_path.parent
            # For each dot beyond the first, go up one directory
            for _ in range(dot_count - 1):
                current_dir = current_dir.parent

            path_str = os.path.join(current_dir, *name_parts)
            possible_paths = [
                Path(f"{path_str}.py"),
                Path(path_str) / "__init__.py"
            ]
        else:
            possible_paths = [
                self.root_dir / f"{path_str}.py",
                self.root_dir / path_str / "__init__.py",
                # Also try to resolve relative to the current file's directory if it's not a root package import
                base_path.parent / f"{path_str}.py",
                base_path.parent / path_str / "__init__.py"
            ]

        return [p.resolve() for p in possible_paths if p.resolve().is_file() and p.resolve() in self.files]

    def build_graph(self):
        """Build the dependency graph by iterating through discovered files."""
        self._find_source_files()

        # Mapping from canonical path string to list of paths that import it
        for file_path in self.files:
            file_path_str = str(file_path.relative_to(self.root_dir))

            if file_path.suffix == '.py':
                result = parse_python_file(str(file_path))
                if result.get('has_dynamic'):
                    self.uncertain_files.add(file_path)

                for imp in result.get('imports', []):
                    resolved_paths = self._resolve_python_import(imp, file_path)
                    for resolved_path in resolved_paths:
                        self.reverse_deps[resolved_path].add(file_path)

            elif file_path.suffix == '.dart':
                result = self._run_dart_parser(file_path)
                if result.get('has_reflection'):
                    self.uncertain_files.add(file_path)

                # Handle Dart imports
                for imp in result.get('imports', []):
                    # We skip 'dart:' and 'package:' imports that aren't local for now,
                    # but if there are relative imports or package: imports that map to local, we should resolve.
                    if imp.startswith('dart:'):
                        continue

                    if imp.startswith('package:'):
                        # Very naive package resolution assuming package name maps to a local directory
                        # E.g., package:my_pkg/file.dart -> lib/file.dart if in a dart project
                        # For this task, we will try to resolve local relative imports.
                        continue

                    # Relative import
                    # Resolve relative to the file's directory
                    target_path = (file_path.parent / imp).resolve()
                    if target_path.is_file() and target_path in self.files:
                        self.reverse_deps[target_path].add(file_path)

                # Dart exports are also dependencies (changing the exported file affects the exporter)
                for exp in result.get('exports', []):
                    target_path = (file_path.parent / exp).resolve()
                    if target_path.is_file() and target_path in self.files:
                        self.reverse_deps[target_path].add(file_path)

    def analyze_impact(self, changed_files: list[str]) -> dict:
        """Find transitively impacted source and test files."""
        # Convert changed files to resolved Paths
        changed_paths = set()
        for f in changed_files:
            p = (self.root_dir / f).resolve()
            if p.is_file() and p in self.files:
                changed_paths.add(p)

        visited = set()
        queue = list(changed_paths)

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Find all files that depend on this file
            if current in self.reverse_deps:
                for dependent in self.reverse_deps[current]:
                    if dependent not in visited:
                        queue.append(dependent)

        impacted_tests = set()
        for v in visited:
            if v in self.test_files:
                impacted_tests.add(v)

        # Handle uncertainty: if any changed file or impacted file has uncertainty,
        # we can't be sure about the exact impact boundary.
        # Thus, we should widen the test scope to include all tests.
        uncertain = False
        if any(f in self.uncertain_files for f in visited):
            uncertain = True
            impacted_tests = self.test_files.copy()

        return {
            'affected_files': sorted([str(p.relative_to(self.root_dir)) for p in visited]),
            'impacted_tests': sorted([str(p.relative_to(self.root_dir)) for p in impacted_tests]),
            'uncertain': uncertain
        }
