import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

class DependencyEngine:
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        self.dart_parser_path = self.repo_root / 'tools' / 'change_impact' / 'dart_parser' / 'parser.dart'
        self.dependencies: Dict[str, Set[str]] = {}  # file -> set of files it depends on
        self.reverse_dependencies: Dict[str, Set[str]] = {}  # file -> set of files depending on it
        self.dynamic_files: Set[str] = set()

    def discover_files(self) -> Tuple[List[str], List[str]]:
        python_files = []
        dart_files = []
        for root, _, files in os.walk(self.repo_root):
            if '.git' in root:
                continue
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
                elif file.endswith('.dart'):
                    dart_files.append(os.path.join(root, file))
        return python_files, dart_files

    def parse_python_file(self, file_path: str):
        rel_path = os.path.relpath(file_path, self.repo_root)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=rel_path)

            deps = set()
            is_dynamic = False

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        deps.add(name.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        deps.add(node.module)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ('__import__', 'eval', 'exec'):
                            is_dynamic = True
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr == 'import_module':
                            is_dynamic = True

            self.dependencies[rel_path] = deps
            if is_dynamic:
                self.dynamic_files.add(rel_path)
        except Exception:
            self.dependencies[rel_path] = set()

    def parse_dart_files(self, dart_files: List[str]):
        if not dart_files:
            return

        # Check if dart parser is available
        try:
            # We can't rely on 'dart' command existence alone, must check parsing
            cmd = ['dart', 'run', str(self.dart_parser_path)] + dart_files
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = result.stdout.strip()

            if "BLOCKED: Missing parser capability" in output:
                print("BLOCKED: Missing parser capability")
                sys.exit(1)

            parsed_data = json.loads(output)

            for file_path, data in parsed_data.items():
                rel_path = os.path.relpath(file_path, self.repo_root)
                self.dependencies[rel_path] = set(data.get('imports', []))
                if data.get('dynamic'):
                    self.dynamic_files.add(rel_path)

        except subprocess.CalledProcessError as e:
            if "Missing parser capability" in e.stdout or "Missing parser capability" in e.stderr:
                print("BLOCKED: Missing parser capability")
                sys.exit(1)
            # If dart itself fails (e.g. not installed), fail with BLOCKED
            print("BLOCKED: Missing parser capability")
            sys.exit(1)
        except FileNotFoundError:
            # dart not found
            print("BLOCKED: Missing parser capability")
            sys.exit(1)

    def resolve_python_import(self, module_name: str, base_file: str) -> Set[str]:
        # Very basic resolution: 'a.b.c' -> 'a/b/c.py' or 'a/b/c/__init__.py'
        parts = module_name.split('.')
        possible_paths = [
            os.path.join(*parts) + '.py',
            os.path.join(*parts, '__init__.py')
        ]
        resolved = set()
        for p in possible_paths:
            full_p = os.path.join(self.repo_root, p)
            if os.path.exists(full_p):
                resolved.add(p)
        return resolved

    def resolve_dart_import(self, uri: str, base_file: str) -> Set[str]:
        resolved = set()
        if uri.startswith('package:'):
            # package:my_pkg/foo.dart -> lib/foo.dart
            # Assuming 'my_pkg' is the current package (which is the case for most intra-repo dependencies)
            parts = uri[len('package:'):].split('/')
            if len(parts) > 1:
                # The first part is the package name. The rest is the path inside lib/
                rel_path = os.path.join('lib', *parts[1:])
                if os.path.exists(os.path.join(self.repo_root, rel_path)):
                    resolved.add(rel_path)
        elif not uri.startswith('dart:'):
            # relative import
            base_dir = os.path.dirname(base_file)
            target_path = os.path.normpath(os.path.join(base_dir, uri))
            if os.path.exists(os.path.join(self.repo_root, target_path)):
                resolved.add(target_path)
        return resolved

    def build_graph(self):
        python_files, dart_files = self.discover_files()

        for pf in python_files:
            self.parse_python_file(pf)

        self.parse_dart_files(dart_files)

        # Build reverse dependencies (resolved)
        for rel_path, deps in self.dependencies.items():
            resolved_deps = set()
            for dep in deps:
                if rel_path.endswith('.py'):
                    resolved_deps.update(self.resolve_python_import(dep, rel_path))
                elif rel_path.endswith('.dart'):
                    resolved_deps.update(self.resolve_dart_import(dep, rel_path))

            for r_dep in resolved_deps:
                if r_dep not in self.reverse_dependencies:
                    self.reverse_dependencies[r_dep] = set()
                self.reverse_dependencies[r_dep].add(rel_path)

    def get_impact(self, changed_files: List[str]) -> Tuple[List[str], List[str]]:
        # Compute affected files and tests
        affected_files = set()
        queue = list(changed_files)
        visited = set()

        # Determine languages involved in changes
        changed_py = any(f.endswith('.py') for f in changed_files)
        changed_dart = any(f.endswith('.dart') for f in changed_files)

        # Widening for dynamic uncertainty
        for df in self.dynamic_files:
            if df.endswith('.py') and changed_py:
                queue.append(df)
            elif df.endswith('.dart') and changed_dart:
                queue.append(df)

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            affected_files.add(node)

            for child in self.reverse_dependencies.get(node, []):
                if child not in visited:
                    queue.append(child)

        # Filter tests
        affected_tests = set()
        for f in affected_files:
            fname = os.path.basename(f)
            if f.endswith('.py') and fname.startswith('test_'):
                affected_tests.add(f)
            elif f.endswith('.dart') and fname.endswith('_test.dart'):
                affected_tests.add(f)

        return sorted(list(affected_files)), sorted(list(affected_tests))
