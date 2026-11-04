import ast
import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple

class ParserBlockedError(Exception):
    pass

class ChangeImpactEngine:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self.dart_parser_script = self.repo_root / 'tools' / 'change_impact' / 'dart_parser' / 'bin' / 'parser.dart'
        self.dart_parser_dir = self.dart_parser_script.parent.parent
        self._dart_initialized = False
        self._dart_cache: Dict[Path, Tuple[List[str], bool]] = {}
        self._dart_cache_populated = False

    def _ensure_dart_initialized(self):
        if self._dart_initialized:
            return

        # Only run pub get if not in a CI/no-dart environment
        if not shutil.which('dart'):
            return

        if not self.dart_parser_script.exists():
            return

        pubspec_lock = self.dart_parser_dir / 'pubspec.lock'
        if not pubspec_lock.exists():
            try:
                subprocess.run(
                    ['dart', 'pub', 'get'],
                    cwd=str(self.dart_parser_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
            except subprocess.CalledProcessError:
                pass

        self._dart_initialized = True


    def find_all_files(self) -> List[Path]:
        files = []
        for root, dirs, filenames in os.walk(self.repo_root):
            # Ignore some common dirs that shouldn't be parsed
            if any(d in root for d in ['.git', '__pycache__', 'node_modules', '.dart_tool']):
                continue
            for filename in filenames:
                if filename.endswith('.py') or filename.endswith('.dart'):
                    files.append(Path(root) / filename)
        return files

    def parse_python_file(self, file_path: Path) -> Tuple[List[str], bool]:
        """Returns (list_of_imported_modules, has_dynamic_imports)"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return [], False

        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            return [], False

        imports = []
        has_dynamic = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                else:
                    # from . import utils
                    for alias in node.names:
                        imports.append(alias.name)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ['__import__', 'getattr']:
                        has_dynamic = True
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'import_module':
                        has_dynamic = True

        return imports, has_dynamic

    def _resolve_python_import(self, module_name: str, source_file: Path) -> List[Path]:
        # Tries to resolve a Python module name to a file path
        # It's an approximation. We assume standard module to path mapping
        # E.g., 'tools.change_impact.engine' -> 'tools/change_impact/engine.py'
        # Return list of potential matches
        parts = module_name.split('.')
        base_path = self.repo_root.joinpath(*parts)
        candidates = [
            base_path.with_suffix('.py'),
            base_path / '__init__.py',
        ]

        # also consider relative to source_file parent (though standard python absolute import from root is common here)
        rel_base_path = source_file.parent.joinpath(*parts)
        candidates.extend([
            rel_base_path.with_suffix('.py'),
            rel_base_path / '__init__.py',
        ])

        return [c for c in candidates if c.is_file()]

    def _populate_dart_cache(self, dart_files: List[Path]):
        if self._dart_cache_populated:
            return
        if not dart_files:
            self._dart_cache_populated = True
            return

        if not shutil.which('dart'):
            print("BLOCKED: Missing parser capability")
            raise ParserBlockedError("BLOCKED: Missing parser capability")
        if not self.dart_parser_script.exists():
            print("BLOCKED: Missing parser capability")
            raise ParserBlockedError("BLOCKED: Missing parser capability")

        self._ensure_dart_initialized()

        try:
            # We assume batch mode dart script returns a map of {filepath: {imports: [...]}}
            result = subprocess.run(
                ['dart', 'run', str(self.dart_parser_script), '--batch'] + [str(p) for p in dart_files],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(self.dart_parser_dir)
            )
            output = result.stdout.strip()
            # To handle possible print output from pub get or warnings, we look for the last line which should be our json
            last_line = output.split('\n')[-1]
            data = json.loads(last_line)

            for file_path_str, info in data.items():
                if 'error' in info:
                    self._dart_cache[Path(file_path_str)] = ([], False)
                else:
                    self._dart_cache[Path(file_path_str)] = (info.get('imports', []), False)

        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, IndexError):
            pass

        self._dart_cache_populated = True

    def parse_dart_file(self, file_path: Path) -> Tuple[List[str], bool]:
        """Returns (list_of_imported_modules, has_dynamic_imports)"""
        # Legacy fallback if cache not used directly
        if not self._dart_cache_populated:
            self._populate_dart_cache([file_path])
        return self._dart_cache.get(file_path, ([], False))

    def _resolve_dart_import(self, import_uri: str, source_file: Path) -> List[Path]:
        if import_uri.startswith('package:'):
            # package:my_pkg/path/to/file.dart -> lib/path/to/file.dart
            uri_parts = import_uri[len('package:'):].split('/')
            if len(uri_parts) > 1:
                # Assuming the package is the current repo for simplicity
                # the path inside the package starts from index 1.
                # It resolves to lib/path/to/file.dart
                pkg_path = self.repo_root / 'lib' / '/'.join(uri_parts[1:])
                if pkg_path.is_file():
                    return [pkg_path]
        elif import_uri.startswith('dart:'):
            return []
        else:
            # Relative import
            resolved = (source_file.parent / import_uri).resolve()
            if resolved.is_file():
                return [resolved]
        return []

    def build_graph(self) -> Tuple[Dict[Path, Set[Path]], bool]:
        """
        Builds a reverse dependency graph: dependency -> set of dependants.
        Returns (graph, has_global_uncertainty)
        """
        all_files = self.find_all_files()
        reverse_graph: Dict[Path, Set[Path]] = {f: set() for f in all_files}
        has_global_uncertainty = False

        dart_files = [f for f in all_files if f.suffix == '.dart']
        if dart_files:
            self._populate_dart_cache(dart_files)

        for f in all_files:
            imports = []
            has_dynamic = False

            if f.suffix == '.py':
                imports, has_dynamic = self.parse_python_file(f)
                if has_dynamic:
                    has_global_uncertainty = True

                for imp in imports:
                    resolved_paths = self._resolve_python_import(imp, f)
                    for rp in resolved_paths:
                        if rp in reverse_graph:
                            reverse_graph[rp].add(f)

            elif f.suffix == '.dart':
                imports, has_dynamic = self.parse_dart_file(f)
                # Dart doesn't have dynamic imports the same way python does, but just in case
                for imp in imports:
                    resolved_paths = self._resolve_dart_import(imp, f)
                    for rp in resolved_paths:
                        if rp in reverse_graph:
                            reverse_graph[rp].add(f)

        return reverse_graph, has_global_uncertainty

    def get_impacted_files(self, changed_files: List[Path], reverse_graph: Dict[Path, Set[Path]], has_global_uncertainty: bool) -> Set[Path]:
        all_files = set(reverse_graph.keys())
        if has_global_uncertainty:
            # Widen the recommended test scope when exact dependency impact cannot be established safely.
            return all_files

        impacted = set(changed_files)
        queue = list(changed_files)

        while queue:
            current = queue.pop(0)
            if current in reverse_graph:
                for dependant in reverse_graph[current]:
                    if dependant not in impacted:
                        impacted.add(dependant)
                        queue.append(dependant)

        return impacted

    def map_to_tests(self, impacted_files: Set[Path]) -> Set[Path]:
        # Affected tests are any impacted file that is a test file
        tests = set()
        for f in impacted_files:
            name = f.name
            if name.startswith('test_') and name.endswith('.py'):
                tests.add(f)
            elif name.endswith('_test.dart'):
                tests.add(f)
        return tests

    def analyze(self, changed_files: List[str]) -> Tuple[List[str], List[str]]:
        changed_paths = []
        for cf in changed_files:
            p = self.repo_root / cf
            if p.is_file():
                changed_paths.append(p)

        reverse_graph, has_global_uncertainty = self.build_graph()

        impacted_paths = self.get_impacted_files(changed_paths, reverse_graph, has_global_uncertainty)
        impacted_tests = self.map_to_tests(impacted_paths)

        def to_rel(paths: Set[Path]) -> List[str]:
            return sorted([str(p.relative_to(self.repo_root)) for p in paths])

        return to_rel(impacted_paths), to_rel(impacted_tests)
