import os
import json
import subprocess
from typing import Dict, List, Set, Tuple

from tools.change_impact.python_parser import extract_python_imports

class ImpactEngine:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        self.dart_parser_bin = os.path.join(self.repo_root, "tools", "change_impact", "dart_parser", "bin", "dart_parser")
        self.dependency_graph: Dict[str, Set[str]] = {}  # imported -> set(importers)
        self.files_scanned: Set[str] = set()
        self.all_tests: Set[str] = set()
        self.dynamic_files: Set[str] = set()

    def _normalize_path(self, path: str) -> str:
        abs_path = os.path.abspath(os.path.join(self.repo_root, path))
        return os.path.relpath(abs_path, self.repo_root)

    def _is_test_file(self, filepath: str) -> bool:
        filename = os.path.basename(filepath)
        return (filename.startswith('test_') and filename.endswith('.py')) or \
               (filename.endswith('_test.dart'))

    def _get_dart_imports(self, filepath: str) -> Tuple[List[str], bool]:
        if not os.path.exists(os.path.join(self.repo_root, filepath)):
            return [], False
        try:
            result = subprocess.run(
                [self.dart_parser_bin, os.path.join(self.repo_root, filepath)],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout.strip()
            if output == "BLOCKED: Missing parser capability":
                print(output)
                return [], True # Treat missing capability as dynamic/uncertain

            try:
                imports = json.loads(output)
                return imports, False
            except json.JSONDecodeError:
                 return [], True
        except subprocess.CalledProcessError:
            print("BLOCKED: Missing parser capability")
            return [], True

    def _resolve_python_import(self, importer_path: str, import_str: str) -> List[str]:
        # Simple resolution for python imports.
        # This resolves a module string like 'tools.change_impact.engine'
        # to a relative filepath 'tools/change_impact/engine.py' or 'tools/change_impact/engine/__init__.py'
        if import_str.startswith('.'):
            # relative import logic
            level = 0
            while import_str.startswith('.'):
                level += 1
                import_str = import_str[1:]

            parts = importer_path.split(os.sep)
            if len(parts) > level:
                base_dir = os.sep.join(parts[:-level])
                import_parts = import_str.split('.')

                # Check .py
                possible_path = os.path.join(base_dir, *import_parts) + '.py'
                if os.path.exists(os.path.join(self.repo_root, possible_path)):
                    return [possible_path]
                # Check __init__.py
                possible_path_init = os.path.join(base_dir, *import_parts, '__init__.py')
                if os.path.exists(os.path.join(self.repo_root, possible_path_init)):
                    return [possible_path_init]
            return []

        import_parts = import_str.split('.')
        possible_path = os.path.join(*import_parts) + '.py'

        results = []
        if os.path.exists(os.path.join(self.repo_root, possible_path)):
             results.append(possible_path)

        possible_path_init = os.path.join(*import_parts, '__init__.py')
        if os.path.exists(os.path.join(self.repo_root, possible_path_init)):
             results.append(possible_path_init)

        return results

    def _resolve_dart_import(self, importer_path: str, import_str: str) -> List[str]:
        # 'dart:core' -> ignore
        if import_str.startswith('dart:'):
            return []

        # 'lib/xyz.dart' from 'package:...'
        if import_str.startswith('lib/'):
             # If importer is in dart_parser project for example, package root is dart_parser/
             # We need to find the project root for the importer.
             parts = importer_path.split(os.sep)
             project_root = ""
             for i in range(len(parts)-1, -1, -1):
                 if parts[i] in ('lib', 'bin', 'test'):
                     project_root = os.sep.join(parts[:i])
                     break

             if project_root:
                 resolved = os.path.join(project_root, import_str)
             else:
                 resolved = import_str

             if os.path.exists(os.path.join(self.repo_root, resolved)):
                 return [resolved]
             return []

        # relative imports like '../foo.dart'
        importer_dir = os.path.dirname(importer_path)
        resolved = os.path.normpath(os.path.join(importer_dir, import_str))
        if os.path.exists(os.path.join(self.repo_root, resolved)):
            return [resolved]
        return []

    def add_file(self, filepath: str):
        filepath = self._normalize_path(filepath)
        if filepath in self.files_scanned:
            return

        if not os.path.exists(os.path.join(self.repo_root, filepath)):
            return

        self.files_scanned.add(filepath)
        if self._is_test_file(filepath):
            self.all_tests.add(filepath)

        if filepath.endswith('.py'):
            imports, is_dynamic = extract_python_imports(os.path.join(self.repo_root, filepath))
            if is_dynamic:
                self.dynamic_files.add(filepath)
            for imp in imports:
                resolved_paths = self._resolve_python_import(filepath, imp)
                for rp in resolved_paths:
                     self.dependency_graph.setdefault(rp, set()).add(filepath)

        elif filepath.endswith('.dart'):
             imports, is_dynamic = self._get_dart_imports(filepath)
             if is_dynamic:
                 self.dynamic_files.add(filepath)
             for imp in imports:
                  resolved_paths = self._resolve_dart_import(filepath, imp)
                  for rp in resolved_paths:
                       self.dependency_graph.setdefault(rp, set()).add(filepath)

    def scan_directory(self, directory: str = "."):
        abs_dir = os.path.abspath(os.path.join(self.repo_root, directory))
        for root, _, files in os.walk(abs_dir):
            for file in files:
                if file.endswith('.py') or file.endswith('.dart'):
                    self.add_file(os.path.relpath(os.path.join(root, file), self.repo_root))

    def get_impacted_tests(self, changed_files: List[str]) -> Tuple[Set[str], Set[str]]:
        """
        Returns a tuple of (impacted_files, impacted_tests).
        """
        impacted_files = set()
        impacted_tests = set()

        # Build the graph fully first so we can traverse reverse dependencies
        # In a real tool we might only scan what's necessary, but we scan all to be safe and build complete graph.

        # Actually, let's make sure the whole repo is scanned so reverse dependencies are known.
        if not self.files_scanned:
             self.scan_directory()

        # Add dynamic scope widening
        # If any file has dynamic imports or syntax errors, we can't be sure of its impact.
        # Widen to all tests in its directory, or even globally if we want to be safe.
        # Let's say if dynamic_files is not empty, and one of them is in the reachable graph from changed_files,
        # we widen the scope for that dynamic file.
        # Wait, if a dynamic file is changed, or depends on a changed file, it might impact ANYTHING.
        # A simple strategy: if a changed file reaches a dynamic file, we add all tests to be safe.

        queue = [self._normalize_path(f) for f in changed_files]
        visited = set()

        widen_scope = False

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)

            impacted_files.add(node)
            if self._is_test_file(node):
                impacted_tests.add(node)

            if node in self.dynamic_files:
                widen_scope = True

            for depender in self.dependency_graph.get(node, []):
                if depender not in visited:
                    queue.append(depender)

        if widen_scope or any(cf in self.dynamic_files for cf in changed_files):
             # To be safe, if we hit uncertain dynamic dependencies, widen scope
             # We'll just add all tests to the impacted tests list.
             impacted_tests = self.all_tests.copy()
             impacted_files.update(self.all_tests)

        return impacted_files, impacted_tests
