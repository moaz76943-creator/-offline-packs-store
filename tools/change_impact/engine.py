import ast
import json
import os
import subprocess
import logging
from typing import Set, Dict, List, Optional, Tuple
from collections import defaultdict

class ChangeImpactEngine:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.dynamic_files: Set[str] = set()
        self.test_ownership: Dict[str, Set[str]] = defaultdict(set)
        self.dart_parser_dir = os.path.join(repo_root, 'tools/change_impact/dart_parser')
        self.dart_parser_script = os.path.join(self.dart_parser_dir, 'bin/parse.dart')
        if not os.path.exists(self.dart_parser_script):
            self.dart_blocked = True
        else:
            self.dart_blocked = False

    def _resolve_python_module(self, module_name: str) -> List[str]:
        # Return all possible resolutions
        parts = module_name.split('.')
        results = []

        path = os.path.join(self.repo_root, *parts) + '.py'
        if os.path.exists(path):
            results.append(os.path.relpath(path, self.repo_root))

        path_init = os.path.join(self.repo_root, *parts, '__init__.py')
        if os.path.exists(path_init):
            results.append(os.path.relpath(path_init, self.repo_root))

        return results

    def parse_python_file(self, file_path: str):
        full_path = os.path.join(self.repo_root, file_path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
            has_dynamic = False

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for resolved in self._resolve_python_module(alias.name):
                            self.dependencies[resolved].add(file_path)

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for resolved in self._resolve_python_module(node.module):
                            self.dependencies[resolved].add(file_path)
                        # Also handle node.names if they are modules
                        for alias in node.names:
                            module_name = node.module + "." + alias.name
                            for resolved in self._resolve_python_module(module_name):
                                self.dependencies[resolved].add(file_path)

                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                        has_dynamic = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                        has_dynamic = True
                    elif isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec'):
                        has_dynamic = True

            if has_dynamic:
                self.dynamic_files.add(file_path)

        except SyntaxError:
            pass

    def _resolve_dart_module(self, uri: str) -> Optional[str]:
        if uri.startswith('package:'):
            return None
        if uri.startswith('dart:'):
            return None
        return uri

    def parse_dart_file(self, file_path: str):
        if self.dart_blocked:
            raise RuntimeError("BLOCKED: Missing parser capability for Dart.")

        full_path = os.path.join(self.repo_root, file_path)
        try:
            result = subprocess.run(
                ['dart', 'run', self.dart_parser_script, full_path],
                capture_output=True, text=True, check=True,
                cwd=self.dart_parser_dir
            )
            data = json.loads(result.stdout)

            for dep in data.get('dependencies', []):
                resolved = self._resolve_dart_module(dep)
                if resolved:
                    abs_dep = os.path.normpath(os.path.join(os.path.dirname(file_path), resolved))
                    if os.path.exists(os.path.join(self.repo_root, abs_dep)):
                        self.dependencies[abs_dep].add(file_path)

            if data.get('has_dynamic', False):
                self.dynamic_files.add(file_path)
            if data.get('syntax_error', False):
                pass

        except subprocess.CalledProcessError as e:
            # Re-raise so the engine knows it failed and can block/report
            raise RuntimeError(f"BLOCKED: Parser failed for {file_path}. Details: {e}")

    def scan_project(self):
        for root, dirs, files in os.walk(self.repo_root):
            if '.git' in dirs:
                dirs.remove('.git')
            if 'dart_parser' in dirs:
                dirs.remove('dart_parser')

            for file in files:
                if file.endswith('.py') or file.endswith('.dart'):
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                    if file.endswith('.py'):
                        self.parse_python_file(rel_path)
                    else:
                        try:
                            self.parse_dart_file(rel_path)
                        except RuntimeError:
                            # Let it bubble up or mark as blocked
                            self.dart_blocked = True

    def get_impacted_files(self, changed_files: List[str]) -> Tuple[Set[str], bool]:
        impacted = set(changed_files)
        queue = list(changed_files)
        visited = set(changed_files)

        widen = False

        if len(self.dynamic_files) > 0:
            widen = True

        while queue:
            current = queue.pop(0)

            for dependent in self.dependencies.get(current, []):
                if dependent not in visited:
                    visited.add(dependent)
                    impacted.add(dependent)
                    queue.append(dependent)

        return impacted, widen

    def map_to_tests(self, impacted_files: Set[str], widen: bool) -> Set[str]:
        tests = set()
        all_tests = set()

        for root, dirs, files in os.walk(self.repo_root):
            if '.git' in dirs:
                dirs.remove('.git')
            if 'dart_parser' in dirs:
                dirs.remove('dart_parser')
            for file in files:
                if (file.startswith('test_') or '_test' in file) and (file.endswith('.py') or file.endswith('.dart')):
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                    all_tests.add(rel_path)

        if widen:
            return all_tests

        for f in impacted_files:
            if f in all_tests:
                tests.add(f)
            else:
                base = os.path.splitext(os.path.basename(f))[0]
                possible_tests = [f"test_{base}.py", f"test_{base}.dart", f"{base}_test.dart", f"{base}_test.py"]
                for t in all_tests:
                    if os.path.basename(t) in possible_tests:
                        tests.add(t)

        return tests

def analyze_changes(repo_root: str, changed_files: List[str]):
    engine = ChangeImpactEngine(repo_root)
    engine.scan_project()

    if engine.dart_blocked and any(f.endswith('.dart') for f in changed_files):
        return {"status": "BLOCKED", "reason": "Missing parser capability"}

    impacted, widen = engine.get_impacted_files(changed_files)
    tests = engine.map_to_tests(impacted, widen)

    return {
        "status": "OK",
        "affected_files": list(impacted),
        "affected_tests": list(tests),
        "widen": widen
    }

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        res = analyze_changes(os.getcwd(), sys.argv[1:])
        print(json.dumps(res, indent=2))
