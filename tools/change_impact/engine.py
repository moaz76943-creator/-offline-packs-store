import ast
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Set, Tuple

class DependencyGraph:
    def __init__(self):
        self.nodes = set()
        self.edges = {}
        self.reverse_edges = {}
        self.uncertain = set()

    def add_node(self, node: str):
        self.nodes.add(node)
        if node not in self.edges:
            self.edges[node] = set()
        if node not in self.reverse_edges:
            self.reverse_edges[node] = set()

    def add_edge(self, u: str, v: str):
        """u depends on v"""
        self.add_node(u)
        self.add_node(v)
        self.edges[u].add(v)
        self.reverse_edges[v].add(u)

    def mark_uncertain(self, node: str):
        self.uncertain.add(node)

    def get_impacted_nodes(self, changed_nodes: List[str]) -> Set[str]:
        impacted = set()
        queue = list(changed_nodes)
        visited = set(changed_nodes)

        while queue:
            node = queue.pop(0)
            impacted.add(node)

            for dependent in self.reverse_edges.get(node, set()):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)

        return impacted

    def needs_widen(self, impacted: Set[str]) -> bool:
        for node in self.uncertain:
            if node in impacted:
                return True
        return False

class ImpactAnalyzer:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self.graph = DependencyGraph()

        self.parser_dir = Path(__file__).parent.resolve() / "dart_parser"
        self._dart_parser_setup_done = False
        self._dart_available = bool(shutil.which("dart"))

    def _setup_dart_parser(self):
        if not self._dart_available:
            return False

        if self._dart_parser_setup_done:
            return True

        # Ensure dependencies are available if not run recently
        # We always want to ensure pub get has run if the tool dir exists but isn't initialized in this session.
        if self.parser_dir.exists():
            pubspec = self.parser_dir / "pubspec.yaml"
            if pubspec.exists():
                subprocess.run(["dart", "pub", "get"], cwd=self.parser_dir, capture_output=True, check=False)

        self._dart_parser_setup_done = True
        return True

    def _resolve_python_import(self, module_name: str, relative_to: Path, level: int = 0) -> List[str]:
        if level > 0:
            parts = module_name.split('.') if module_name else []
            curr = relative_to.parent
            for _ in range(level - 1):
                curr = curr.parent
            path_parts = list(curr.parts) + parts
            try:
                Path(*path_parts).relative_to(self.base_dir)
            except ValueError:
                return []
        else:
            parts = module_name.split('.')
            path_parts = [str(self.base_dir)] + parts

        results = []

        potential_file = Path(*path_parts).with_suffix('.py')
        if potential_file.exists() and potential_file.is_file():
            try:
                results.append(str(potential_file.relative_to(self.base_dir)))
            except ValueError:
                pass

        potential_dir = Path(*path_parts) / '__init__.py'
        if potential_dir.exists() and potential_dir.is_file():
            try:
                results.append(str(potential_dir.relative_to(self.base_dir)))
            except ValueError:
                pass

        return results

    def analyze_python_file(self, filepath: Path) -> None:
        try:
            rel_path = str(filepath.relative_to(self.base_dir))
        except ValueError:
            return

        self.graph.add_node(rel_path)

        try:
            tree = ast.parse(filepath.read_text(encoding='utf-8'), filename=str(filepath))
        except SyntaxError:
            self.graph.mark_uncertain(rel_path)
            return

        has_dynamic = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved_paths = self._resolve_python_import(alias.name, filepath)
                    for rp in resolved_paths:
                        self.graph.add_edge(rel_path, rp)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    resolved_paths = self._resolve_python_import(node.module, filepath, node.level)
                    for rp in resolved_paths:
                        self.graph.add_edge(rel_path, rp)

                    for alias in node.names:
                        full_name = f"{node.module}.{alias.name}"
                        sub_resolved = self._resolve_python_import(full_name, filepath, node.level)
                        for rp in sub_resolved:
                            self.graph.add_edge(rel_path, rp)
                else:
                    resolved_paths = self._resolve_python_import('', filepath, node.level)
                    for rp in resolved_paths:
                        self.graph.add_edge(rel_path, rp)

                    for alias in node.names:
                        sub_resolved = self._resolve_python_import(alias.name, filepath, node.level)
                        for rp in sub_resolved:
                            self.graph.add_edge(rel_path, rp)

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                    has_dynamic = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                    has_dynamic = True

        if has_dynamic:
            self.graph.mark_uncertain(rel_path)

    def analyze_dart_file(self, filepath: Path) -> None:
        try:
            rel_path = str(filepath.relative_to(self.base_dir))
        except ValueError:
            return

        self.graph.add_node(rel_path)

        if not self._setup_dart_parser():
            print("BLOCKED: Dart SDK not available")
            self.graph.mark_uncertain(rel_path)
            return

        try:
            result = subprocess.run(
                ["dart", "run", "parse.dart", str(filepath.resolve())],
                cwd=self.parser_dir,
                capture_output=True,
                text=True,
                check=True
            )
            out = result.stdout.strip()

            if not out:
                self.graph.mark_uncertain(rel_path)
                return

            lines = out.split('\n')
            last_line = lines[-1]
            try:
                data = json.loads(last_line)
            except json.JSONDecodeError:
                self.graph.mark_uncertain(rel_path)
                return

            if 'error' in data:
                self.graph.mark_uncertain(rel_path)
                return

            deps = data.get('imports', [])
            for dep in deps:
                if dep.startswith('dart:') or dep.startswith('package:'):
                    continue
                else:
                    resolved_path = (filepath.parent / dep).resolve()
                    if resolved_path.exists():
                        try:
                            rel_dep = str(resolved_path.relative_to(self.base_dir))
                            self.graph.add_edge(rel_path, rel_dep)
                        except ValueError:
                            pass

        except Exception:
            self.graph.mark_uncertain(rel_path)

    def scan_directory(self) -> None:
        ignored_dirs = {'.git', 'dart_parser', '.venv', 'venv', 'node_modules', '__pycache__', 'build', 'dist', '.dart_tool'}
        for root, dirs, files in os.walk(self.base_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]

            for file in files:
                filepath = Path(root) / file
                if file.endswith('.py'):
                    self.analyze_python_file(filepath)
                elif file.endswith('.dart'):
                    self.analyze_dart_file(filepath)

    def get_impact_report(self, changed_files: List[str]) -> Dict:
        self.scan_directory()

        valid_changed = [f for f in changed_files if f in self.graph.nodes]
        impacted_nodes = self.graph.get_impacted_nodes(valid_changed)

        tests_impacted = set()
        other_impacted = set()

        for node in impacted_nodes:
            name = Path(node).name
            if name.startswith('test_') or name.endswith('_test.py') or name.endswith('_test.dart'):
                tests_impacted.add(node)
            else:
                other_impacted.add(node)

        needs_widen = self.graph.needs_widen(impacted_nodes)

        if self.graph.uncertain:
            needs_widen = True

        return {
            "changed_files": valid_changed,
            "impacted_files": list(other_impacted),
            "impacted_tests": list(tests_impacted),
            "widen_scope": needs_widen,
            "uncertain_nodes": list(self.graph.uncertain)
        }

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 engine.py <changed_file1> <changed_file2> ...")
        sys.exit(1)

    analyzer = ImpactAnalyzer(Path("."))
    report = analyzer.get_impact_report(sys.argv[1:])
    print(json.dumps(report, indent=2))
