import ast
import json
import os
import subprocess
from typing import Dict, List, Set, Tuple, Any

class DependencyEngine:
    def __init__(self, repo_root: str):
        if not os.path.isdir(repo_root):
            raise RuntimeError(f"Repository access is unavailable: {repo_root}")

        self.repo_root = repo_root
        self.dart_parser_path = os.path.join(
            repo_root, "tools", "change_impact", "dart_parser", "bin", "parse.dart"
        )
        # file_path -> list of (imported_file_path or module_name)
        self.forward_graph: Dict[str, Set[str]] = {}
        # file_path -> has_reflection
        self.reflection_nodes: Set[str] = set()
        # file_path -> syntax_error
        self.syntax_error_nodes: Set[str] = set()

    def _resolve_python_import(self, current_file: str, module_name: str) -> str:
        """Attempt to resolve a python module to a local filepath"""
        parts = module_name.split('.')

        # Try relative to repo root
        path_py = os.path.join(self.repo_root, *parts) + ".py"
        path_init = os.path.join(self.repo_root, *parts, "__init__.py")

        if os.path.isfile(path_py):
            return os.path.relpath(path_py, self.repo_root)
        if os.path.isfile(path_init):
            return os.path.relpath(path_init, self.repo_root)

        # Try relative to current file dir
        curr_dir = os.path.dirname(os.path.join(self.repo_root, current_file))
        rel_py = os.path.join(curr_dir, *parts) + ".py"
        rel_init = os.path.join(curr_dir, *parts, "__init__.py")

        if os.path.isfile(rel_py):
            return os.path.relpath(rel_py, self.repo_root)
        if os.path.isfile(rel_init):
            return os.path.relpath(rel_init, self.repo_root)

        return module_name # Unresolved, keep as module name

    def _resolve_dart_import(self, current_file: str, uri: str) -> str:
        """Attempt to resolve dart URI to a local filepath"""
        if uri.startswith('dart:'):
            return uri
        if uri.startswith('package:'):
            # Simplistic mapping: package:my_pkg/path.dart -> path.dart or lib/path.dart
            path_part = uri.split('/', 1)[-1]
            # Best effort
            for prefix in ['', 'lib']:
                candidate = os.path.join(self.repo_root, prefix, path_part)
                if os.path.isfile(candidate):
                    return os.path.relpath(candidate, self.repo_root)
            return uri

        # Relative import
        curr_dir = os.path.dirname(os.path.join(self.repo_root, current_file))
        candidate = os.path.normpath(os.path.join(curr_dir, uri))
        if os.path.isfile(candidate):
            return os.path.relpath(candidate, self.repo_root)

        return uri

    def _parse_python_file(self, filepath: str) -> Tuple[List[str], bool, bool]:
        """Returns (imports, has_reflection, has_syntax_error)"""
        abs_path = os.path.join(self.repo_root, filepath)
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=abs_path)

            imports = []
            has_reflection = False

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                        if alias.name in ('importlib', 'inspect'):
                            has_reflection = True
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
                        if node.module in ('importlib', 'inspect'):
                            has_reflection = True
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ('eval', 'exec', '__import__', 'getattr', 'setattr', 'hasattr'):
                            has_reflection = True
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in ('import_module', 'getmembers'):
                            has_reflection = True

            resolved_imports = [self._resolve_python_import(filepath, imp) for imp in imports]
            return resolved_imports, has_reflection, False
        except SyntaxError:
            return [], False, True
        except Exception:
            return [], False, True

    def _parse_dart_file(self, filepath: str) -> Tuple[List[str], bool, bool]:
        """Returns (imports, has_reflection, has_syntax_error)"""
        if not os.path.exists(self.dart_parser_path):
            raise RuntimeError("BLOCKED: Dart parser capability is missing.")

        abs_path = os.path.join(self.repo_root, filepath)
        try:
            result = subprocess.run(
                ["dart", "run", self.dart_parser_path, abs_path],
                capture_output=True,
                text=True,
                check=False,
                cwd=os.path.dirname(self.dart_parser_path)
            )

            if result.returncode != 0 and not result.stdout.strip():
                # If command fails and no output, consider it a syntax error
                return [], False, True

            out = result.stdout.strip()
            # Find JSON payload
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                # Sometimes flutter/dart prints warnings before json
                lines = out.split('\n')
                for line in reversed(lines):
                    try:
                        data = json.loads(line)
                        break
                    except:
                        pass
                else:
                    return [], False, True

            if "error" in data and not data.get("imports"):
                return [], False, data.get("syntax_errors", True)

            raw_imports = data.get("imports", [])
            resolved = [self._resolve_dart_import(filepath, imp) for imp in raw_imports]
            return resolved, data.get("has_reflection", False), data.get("syntax_errors", False)
        except Exception:
            return [], False, True

    def add_file_to_graph(self, filepath: str) -> None:
        if filepath.endswith('.py'):
            imports, has_refl, has_syn_err = self._parse_python_file(filepath)
        elif filepath.endswith('.dart'):
            imports, has_refl, has_syn_err = self._parse_dart_file(filepath)
        else:
            return

        self.forward_graph[filepath] = set(imports)
        if has_refl:
            self.reflection_nodes.add(filepath)
        if has_syn_err:
            self.syntax_error_nodes.add(filepath)

    def scan_tree(self) -> None:
        """Scan all relevant files in repo to build complete graph."""
        for root, _, files in os.walk(self.repo_root):
            if '.git' in root or '.dart_tool' in root:
                continue
            for file in files:
                if file.endswith('.py') or file.endswith('.dart'):
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                    self.add_file_to_graph(rel_path)

    def is_test_file(self, filepath: str) -> bool:
        basename = os.path.basename(filepath)
        return basename.startswith('test_') or basename.endswith('_test.dart') or basename.endswith('_test.py')

    def map_impact(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        Given a list of changed files, determine impacted files and tests.
        Returns {"affected_files": [...], "affected_tests": [...], "widened": bool}
        """
        # Ensure files are in graph
        for f in changed_files:
            if f not in self.forward_graph:
                self.add_file_to_graph(f)

        # Build reverse dependency graph dynamically based on forward graph
        reverse_graph: Dict[str, Set[str]] = {}
        for f, deps in self.forward_graph.items():
            for d in deps:
                if d not in reverse_graph:
                    reverse_graph[d] = set()
                reverse_graph[d].add(f)

        affected_files = set()
        affected_tests = set()
        widened = False

        queue = list(changed_files)

        # Determine if we need to widen
        # We widen if any changed file or a dependent file uses reflection

        while queue:
            curr = queue.pop(0)
            if curr in affected_files:
                continue

            affected_files.add(curr)

            if curr in self.reflection_nodes:
                widened = True

            if self.is_test_file(curr):
                affected_tests.add(curr)

            for dependent in reverse_graph.get(curr, []):
                if dependent not in affected_files:
                    queue.append(dependent)

        # If widened, we essentially mark everything known as affected, or we can just flag it.
        # The prompt says: "Widen the recommended test scope when exact dependency impact cannot be established safely."
        # We'll include all known tests in the repo if widened.
        if widened:
            for f in self.forward_graph.keys():
                if self.is_test_file(f):
                    affected_tests.add(f)
                else:
                    affected_files.add(f)

        return {
            "affected_files": sorted(list(affected_files)),
            "affected_tests": sorted(list(affected_tests)),
            "widened": widened
        }
