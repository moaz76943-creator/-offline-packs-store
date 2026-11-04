import ast
import json
import os
import subprocess
from pathlib import Path
from collections import defaultdict, deque
from typing import Optional, List, Set, Tuple

class DependencyEngine:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        if not os.access(self.root, os.R_OK | os.X_OK):
            raise RuntimeError(f"Unauthorized or inaccessible root directory: {self.root}")

        self.dart_parser_script = Path(__file__).resolve().parent / "dart_parser" / "bin" / "parser.dart"
        self.graph = defaultdict(set) # source file -> dependent files
        self.dynamic_imports_detected = False
        self.tests_manifest = {} # test_id -> list of files it covers (not used for building the graph, but for mapping)

    def _resolve_python_import(self, module_name: str, base_path: Path, level: int = 0) -> Optional[Path]:
        parts = []
        if module_name:
            parts = module_name.split('.')

        if level > 0:
            # Handle relative imports
            # level=1 means current directory, level=2 means parent, etc.
            current_dir = base_path
            for _ in range(level - 1):
                current_dir = current_dir.parent
                if current_dir == self.root.parent: # Don't go above root
                    return None

            pkg_path = current_dir.joinpath(*parts, '__init__.py')
            if pkg_path.exists():
                return pkg_path

            mod_path = current_dir.joinpath(*parts).with_suffix('.py')
            if mod_path.exists():
                return mod_path

        else:
            if not module_name:
                 return None
            # Absolute import, try finding it relative to the root first
            # 1. As a package (__init__.py)
            pkg_path = self.root.joinpath(*parts, '__init__.py')
            if pkg_path.exists():
                return pkg_path

            # 2. As a module (.py)
            mod_path = self.root.joinpath(*parts).with_suffix('.py')
            if mod_path.exists():
                return mod_path

        return None

    def _parse_python_file(self, file_path: Path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            return # Syntax errors are ignored during graph building or handled in tests

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._resolve_python_import(alias.name, file_path.parent)
                    if resolved:
                        self.graph[str(resolved)].add(str(file_path))
            elif isinstance(node, ast.ImportFrom):
                # Always resolve the module/package part
                resolved_base = self._resolve_python_import(node.module, file_path.parent, level=node.level)
                if resolved_base:
                     self.graph[str(resolved_base)].add(str(file_path))

                # Try to resolve specific imported items as submodules
                for alias in node.names:
                     full_name = f"{node.module}.{alias.name}" if node.module else alias.name
                     resolved_item = self._resolve_python_import(full_name, file_path.parent, level=node.level)
                     if resolved_item:
                         self.graph[str(resolved_item)].add(str(file_path))

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    self.dynamic_imports_detected = True
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'import_module':
                        self.dynamic_imports_detected = True

    def _parse_dart_file(self, file_path: Path):
        try:
            dart_dir = self.dart_parser_script.parent.parent
            if not (dart_dir / ".dart_tool").exists():
                 subprocess.run(["dart", "pub", "get"], cwd=dart_dir, capture_output=True, check=False)

            result = subprocess.run(
                ["dart", "run", str(self.dart_parser_script), str(file_path)],
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)

            if 'error' in data:
                # Handle parser missing
                if 'Could not find a command named' in data['error'] or 'No active package' in data['error']:
                     raise RuntimeError("BLOCKED: Missing parser capability")
                return
            if 'errors' in data:
                return # Syntax errors

            if data.get('has_dynamic'):
                self.dynamic_imports_detected = True

            for uri in data.get('imports', []) + data.get('exports', []):
                # We only track local dependencies (file paths, not package: or dart:)
                if not uri.startswith('dart:') and not uri.startswith('package:'):
                    # Resolve relative to the file path
                    resolved = (file_path.parent / uri).resolve()
                    if resolved.is_relative_to(self.root) and resolved.exists():
                        self.graph[str(resolved)].add(str(file_path))

        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
            # If dart isn't installed or command fails
            if isinstance(e, FileNotFoundError):
                 raise RuntimeError("BLOCKED: Missing parser capability")
            if isinstance(e, subprocess.CalledProcessError):
               if e.returncode == 253 or "Could not find a command named" in e.stderr or "No active package" in e.stderr:
                   raise RuntimeError("BLOCKED: Missing parser capability")
            pass

    def build_graph(self):
        self.graph.clear()
        self.dynamic_imports_detected = False

        for root_dir, _, files in os.walk(self.root):
            for file in files:
                file_path = Path(root_dir) / file
                if not file_path.exists():
                    continue

                # Skip .git, etc
                if '.git' in file_path.parts or '__pycache__' in file_path.parts or '.dart_tool' in file_path.parts:
                    continue

                if file_path.suffix == '.py':
                    self._parse_python_file(file_path)
                elif file_path.suffix == '.dart':
                    self._parse_dart_file(file_path)

    def load_manifest(self, manifest_path: str):
        manifest_file = Path(manifest_path)
        if not manifest_file.exists():
             return
        with open(manifest_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.tests_manifest = data

    def get_impacted_tests(self, changed_files: List[str]) -> Tuple[Set[str], Set[str]]:
        impacted_files = set()
        queue = deque()

        for f in changed_files:
            abs_f = str(Path(self.root / f).resolve())
            queue.append(abs_f)
            impacted_files.add(abs_f)

        while queue:
            current = queue.popleft()
            for dependent in self.graph[current]:
                if dependent not in impacted_files:
                    impacted_files.add(dependent)
                    queue.append(dependent)

        if self.dynamic_imports_detected:
            # Widen scope: run all tests
            return set(self.tests_manifest.keys()), impacted_files

        impacted_tests = set()
        for test_id, covered_files in self.tests_manifest.items():
            for covered_file in covered_files:
                abs_covered = str(Path(self.root / covered_file).resolve())
                if abs_covered in impacted_files:
                    impacted_tests.add(test_id)
                    break

        return impacted_tests, impacted_files
