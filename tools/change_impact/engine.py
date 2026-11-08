import ast
import os
import json
import subprocess
from collections import defaultdict, deque
from pathlib import Path
import sys

def install_repo_import_path():
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

def _check_access(repo_root):
    if not os.access(repo_root, os.R_OK | os.X_OK):
        raise PermissionError("Repository root not accessible")

class DependencyEngine:
    def __init__(self, repo_root):
        self.repo_root = Path(repo_root).resolve()
        _check_access(self.repo_root)
        self.dart_parser_path = self.repo_root / "tools/change_impact/dart_parser.dart"
        if not self.dart_parser_path.exists():
            raise RuntimeError("BLOCKED: Missing dart parser capability")
        self.graph = defaultdict(set)
        self.reverse_graph = defaultdict(set)
        self.uncertain_modules = set()

        # explicitly ensure dart dependencies are available locally without hardcoding paths
        subprocess.run(["dart", "pub", "get"], cwd=str(self.repo_root / "tools" / "change_impact"), capture_output=True)

    def _resolve_python_import(self, module_name, base_path, level=0):
        if level > 0:
            current_dir = base_path.parent
            for _ in range(level - 1):
                current_dir = current_dir.parent

            if module_name:
                parts = module_name.split('.')
                path = current_dir.joinpath(*parts).with_suffix('.py')
                if path.exists():
                    return str(path.relative_to(self.repo_root))

                path = current_dir.joinpath(*parts, '__init__.py')
                if path.exists():
                    return str(path.relative_to(self.repo_root))
            else:
                path = current_dir.joinpath('__init__.py')
                if path.exists():
                    return str(path.relative_to(self.repo_root))
            return None

        parts = module_name.split('.')
        path = self.repo_root.joinpath(*parts).with_suffix('.py')
        if path.exists():
            return str(path.relative_to(self.repo_root))

        path = self.repo_root.joinpath(*parts, '__init__.py')
        if path.exists():
            return str(path.relative_to(self.repo_root))

        return None

    def _resolve_dart_import(self, uri, base_path):
        if uri.startswith('package:') or uri.startswith('dart:'):
            return None

        target = (base_path.parent / uri).resolve()
        try:
            if target.exists():
                return str(target.relative_to(self.repo_root))
        except ValueError:
            pass
        return None

    def extract_python(self, file_path):
        install_repo_import_path()
        rel_path = str(Path(file_path).resolve().relative_to(self.repo_root))
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
        except SyntaxError:
            self.uncertain_modules.add(rel_path)
            return

        uncertain = False
        deps = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._resolve_python_import(alias.name, Path(file_path))
                    if resolved: deps.add(resolved)
            elif isinstance(node, ast.ImportFrom):
                level = node.level if hasattr(node, 'level') else 0

                resolved = self._resolve_python_import(node.module if node.module else "", Path(file_path), level)
                if resolved: deps.add(resolved)

                for alias in node.names:
                    full_name = f"{node.module}.{alias.name}" if node.module else alias.name
                    resolved_sub = self._resolve_python_import(full_name, Path(file_path), level)
                    if resolved_sub: deps.add(resolved_sub)

            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"__import__", "getattr", "eval", "exec"}:
                    uncertain = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
                    uncertain = True

        if uncertain:
            self.uncertain_modules.add(rel_path)
        for dep in deps:
            self.graph[rel_path].add(dep)
            self.reverse_graph[dep].add(rel_path)

    def extract_dart(self, file_path):
        install_repo_import_path()
        rel_path = str(Path(file_path).resolve().relative_to(self.repo_root))

        result = subprocess.run(
            ["dart", "run", str(self.dart_parser_path), str(file_path)],
            cwd=str(self.repo_root / "tools" / "change_impact"),
            capture_output=True, text=True
        )
        if result.returncode != 0:
            self.uncertain_modules.add(rel_path)
            return

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.uncertain_modules.add(rel_path)
            return

        if data.get('error') == 'syntax_error' or data.get('uncertain'):
            self.uncertain_modules.add(rel_path)

        deps = set()
        for dep_uri in data.get('deps', []):
            resolved = self._resolve_dart_import(dep_uri, Path(file_path))
            if resolved: deps.add(resolved)

        for dep in deps:
            self.graph[rel_path].add(dep)
            self.reverse_graph[dep].add(rel_path)

    def map_impact(self, changed_files):
        install_repo_import_path()
        affected_files = set(changed_files)
        queue = deque(changed_files)

        while queue:
            current = queue.popleft()
            for dependent in self.reverse_graph.get(current, []):
                if dependent not in affected_files:
                    affected_files.add(dependent)
                    queue.append(dependent)

        # Widen if uncertain
        if any(f in self.uncertain_modules for f in affected_files):
            from tools.ci_policy.run_scoped_pr_tests import ORDER
            return list(ORDER)

        from tools.ci_policy.run_scoped_pr_tests import select_suites
        return list(select_suites(list(affected_files)))

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 engine.py <changed_file1> <changed_file2> ...")
        sys.exit(1)

    engine = DependencyEngine(os.getcwd())

    for root, _, files in os.walk(engine.repo_root):
        if any(x in root for x in ['.git', '__pycache__', 'node_modules', '.pub-cache']):
            continue
        for file in files:
            path = Path(root) / file
            if path.suffix == '.py':
                engine.extract_python(path)
            elif path.suffix == '.dart':
                engine.extract_dart(path)

    impacted_tests = engine.map_impact(sys.argv[1:])
    print(json.dumps({
        "impacted_tests": impacted_tests
    }))

if __name__ == "__main__":
    main()
