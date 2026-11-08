import ast
import json
import os
import subprocess
from pathlib import Path

class DependencyEngine:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        if not os.access(self.repo_root, os.R_OK | os.X_OK):
            raise PermissionError("Repository root is not readable/accessible")
        self.graph = {} # node -> set of dependencies
        self.reverse_graph = {} # node -> set of nodes that depend on it
        self.uncertain_nodes = set()
        self.engine_dir = Path(__file__).parent.resolve()

    def _normalize_path(self, filepath: Path) -> str:
        return str(filepath.resolve().relative_to(self.repo_root))

    def parse_python_file(self, filepath: Path):
        rel_path = self._normalize_path(filepath)
        deps = set()
        uncertain = False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=str(filepath))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        deps.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    level = node.level or 0

                    if level > 0:
                        # Construct a relative import using dot prefixes
                        prefix = "." * level
                        full_module = prefix + module if module else prefix
                        for alias in node.names:
                            deps.add(f"{full_module}.{alias.name}" if module else f"{prefix}{alias.name}")
                    else:
                        for alias in node.names:
                            deps.add(f"{module}.{alias.name}")
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == '__import__':
                        uncertain = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module':
                        uncertain = True
        except SyntaxError:
            uncertain = True
        except Exception:
            uncertain = True

        self.graph[rel_path] = deps
        if uncertain:
            self.uncertain_nodes.add(rel_path)

    def parse_dart_file(self, filepath: Path):
        rel_path = self._normalize_path(filepath)
        parser_script = self.engine_dir / "dart_parser.dart"

        try:
            result = subprocess.run(
                ["dart", str(parser_script), str(filepath)],
                cwd=str(self.engine_dir),
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)

            deps = set(data.get("dependencies", []))
            uncertain = data.get("uncertain", False)

            self.graph[rel_path] = deps
            if uncertain:
                self.uncertain_nodes.add(rel_path)
        except FileNotFoundError:
            # dart executable not found
            print("BLOCKED")
            import sys
            sys.exit(1)
        except Exception as e:
            # E.g., dart parser failed to run (missing pub dependencies, etc.)
            if "package:analyzer" in str(e) or (hasattr(e, 'stderr') and e.stderr and "package:analyzer" in e.stderr):
                # Try running pub get first before giving up
                subprocess.run(["dart", "pub", "get"], cwd=str(self.engine_dir), capture_output=True)
                try:
                    result = subprocess.run(
                        ["dart", str(parser_script), str(filepath)],
                        cwd=str(self.engine_dir),
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    data = json.loads(result.stdout)

                    deps = set(data.get("dependencies", []))
                    uncertain = data.get("uncertain", False)

                    self.graph[rel_path] = deps
                    if uncertain:
                        self.uncertain_nodes.add(rel_path)
                    return
                except Exception:
                    pass
            print("BLOCKED")
            import sys
            sys.exit(1)

    def build_graph(self):
        self.reverse_graph = {node: set() for node in self.graph}

        for node, deps in self.graph.items():
            for dep in deps:
                resolved_dep = self._resolve_dep_to_file(node, dep)
                if resolved_dep and resolved_dep in self.reverse_graph:
                    self.reverse_graph[resolved_dep].add(node)
                elif resolved_dep and resolved_dep not in self.reverse_graph:
                    self.reverse_graph[resolved_dep] = {node}

    def _resolve_dep_to_file(self, source_node: str, dep: str):
        if source_node.endswith(".dart"):
            if not dep.startswith("dart:") and not dep.startswith("package:"):
                source_path = self.repo_root / source_node
                resolved = (source_path.parent / dep).resolve()
                if resolved.is_file():
                    try:
                        return str(resolved.relative_to(self.repo_root))
                    except ValueError:
                        return None
            return None
        elif source_node.endswith(".py"):
            source_path = self.repo_root / source_node

            # Handle relative python imports
            if dep.startswith("."):
                level = len(dep) - len(dep.lstrip("."))
                # Go up 'level' directories from the current file's directory
                # level=1 means same directory. level=2 means parent dir, etc.
                base_dir = source_path.parent
                for _ in range(level - 1):
                    base_dir = base_dir.parent

                parts = dep.lstrip(".").split(".")

                # Check for module path or file path within relative dir
                for i in range(len(parts), -1, -1):
                    sub_parts = parts[:i]
                    potential_paths = [
                        base_dir.joinpath(*sub_parts).with_suffix(".py"),
                        base_dir.joinpath(*sub_parts) / "__init__.py"
                    ]
                    for p in potential_paths:
                        if p.is_file():
                            try:
                                return str(p.relative_to(self.repo_root))
                            except ValueError:
                                pass
                return None

            else:
                # Absolute import resolution
                parts = dep.split(".")

                for i in range(len(parts), 0, -1):
                    sub_parts = parts[:i]
                    potential_paths = [
                        self.repo_root.joinpath(*sub_parts).with_suffix(".py"),
                        self.repo_root.joinpath(*sub_parts) / "__init__.py"
                    ]
                    for p in potential_paths:
                        if p.is_file():
                            try:
                                return str(p.relative_to(self.repo_root))
                            except ValueError:
                                pass
                return None

    def calculate_impact(self, changed_files: list[str]) -> set[str]:
        impacted = set()
        queue = list(changed_files)
        visited = set()

        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            impacted.add(node)

            if node in self.uncertain_nodes:
                node_path = self.repo_root / node
                if node_path.parent.exists():
                    for f in node_path.parent.glob("*.py"):
                        try:
                            queue.append(self._normalize_path(f))
                        except ValueError:
                            pass
                    for f in node_path.parent.glob("*.dart"):
                        try:
                            queue.append(self._normalize_path(f))
                        except ValueError:
                            pass

            if node in self.reverse_graph:
                queue.extend(self.reverse_graph[node])

        return impacted
