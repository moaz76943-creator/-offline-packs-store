import ast
import os
import sys
import json
import subprocess
from typing import Dict, List, Set, Tuple

class DependencyGraph:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        if not os.access(self.repo_root, os.R_OK):
            raise Exception("Repository access is unavailable")
        self.dependencies: Dict[str, Set[str]] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = {}
        self.uncertain_nodes: Set[str] = set()

    def add_edge(self, source: str, target: str):
        if source not in self.dependencies:
            self.dependencies[source] = set()
        self.dependencies[source].add(target)

        if target not in self.reverse_dependencies:
            self.reverse_dependencies[target] = set()
        self.reverse_dependencies[target].add(source)

    def mark_uncertain(self, node: str):
        self.uncertain_nodes.add(node)

    def analyze_python_file(self, rel_path: str):
        full_path = os.path.join(self.repo_root, rel_path)
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=full_path)
        except Exception:
            self.mark_uncertain(rel_path)
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._resolve_python_import(alias.name, rel_path)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._resolve_python_import(node.module, rel_path, node.level)
                else:
                    self.mark_uncertain(rel_path) # Relative import without module
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    self.mark_uncertain(rel_path)
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                    self.mark_uncertain(rel_path)

    def _resolve_python_import(self, module_name: str, source_rel_path: str, level: int = 0):
        if level > 0:
            parts = os.path.dirname(source_rel_path).split(os.sep)
            if level > len(parts):
                self.mark_uncertain(source_rel_path)
                return
            base_dir = os.sep.join(parts[:-level] if level < len(parts) else [])
            if module_name:
                target_module = f"{base_dir.replace(os.sep, '.')}.{module_name}" if base_dir else module_name
            else:
                target_module = base_dir.replace(os.sep, '.')
        else:
            target_module = module_name

        parts = target_module.split('.')

        # Check if it resolves to a file in the repo
        target_path = os.path.join(self.repo_root, *parts) + '.py'
        target_init_path = os.path.join(self.repo_root, *parts, '__init__.py')

        if os.path.exists(target_path):
            self.add_edge(source_rel_path, os.path.relpath(target_path, self.repo_root))
        elif os.path.exists(target_init_path):
            self.add_edge(source_rel_path, os.path.relpath(target_init_path, self.repo_root))

    def analyze_dart_files(self):
        dart_parser_script = os.path.join(os.path.dirname(__file__), 'dart_parser.dart')
        try:
            result = subprocess.run(['dart', 'run', dart_parser_script, self.repo_root],
                                    capture_output=True, text=True, check=True)
            dart_data = json.loads(result.stdout)
            for file_path, data in dart_data.items():
                for dep in data['dependencies']:
                    self.add_edge(file_path, dep)
                if data['has_uncertainty']:
                    self.mark_uncertain(file_path)
        except subprocess.CalledProcessError:
             raise Exception("BLOCKED: Missing parser capability")
        except FileNotFoundError:
             raise Exception("BLOCKED: Missing parser capability")

    def build_graph(self):
        for root, _, files in os.walk(self.repo_root):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                if '.dart_tool' in rel_path or rel_path.endswith('pubspec.yaml'):
                    continue
                if file.endswith('.py'):
                    self.analyze_python_file(rel_path)

        self.analyze_dart_files()

    def get_impacted_tests(self, changed_files: List[str]) -> Tuple[List[str], List[str]]:
        impacted_files = set()
        queue = list(changed_files)

        while queue:
            node = queue.pop(0)
            if node not in impacted_files:
                impacted_files.add(node)
                if node in self.reverse_dependencies:
                    queue.extend(self.reverse_dependencies[node])

        # Widen scope if uncertainty exists in path
        if self.uncertain_nodes.intersection(impacted_files):
            # For simplicity, if we hit an uncertain node, we return all tests as a fallback
            # A more nuanced approach would be to return tests in the same directory/module
            all_tests = []
            all_files = []
            for root, _, files in os.walk(self.repo_root):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), self.repo_root)
                    if file.startswith('test_') or file.endswith('_test.dart'):
                        all_tests.append(rel_path)
                    if file.endswith('.py') or file.endswith('.dart'):
                        all_files.append(rel_path)
            return sorted(all_files), sorted(all_tests)

        impacted_tests = [f for f in impacted_files if f.startswith('test_') or f.endswith('_test.dart') or 'test' in f]
        return sorted(list(impacted_files)), sorted(impacted_tests)

def get_impact(repo_root: str, changed_files: List[str]):
    graph = DependencyGraph(repo_root)
    graph.build_graph()
    return graph.get_impacted_tests(changed_files)
