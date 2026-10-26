import os
import ast
import json
import subprocess
from pathlib import Path
from typing import List, Set, Dict, Tuple

class DependencyVisitor(ast.NodeVisitor):
    def __init__(self, current_module: str):
        self.dependencies: Set[str] = set()
        self.has_dynamic_imports = False
        self.current_module = current_module

    def visit_Import(self, node):
        for alias in node.names:
            self.dependencies.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.level > 0:
            if self.current_module:
                parts = self.current_module.split(".")
                if len(parts) >= node.level:
                    base = ".".join(parts[:-node.level])
                    if node.module:
                        base = f"{base}.{node.module}" if base else node.module

                    if base:
                        for alias in node.names:
                            self.dependencies.add(f"{base}.{alias.name}")
                            self.dependencies.add(base)
                    else:
                        for alias in node.names:
                            self.dependencies.add(alias.name)
                else:
                    self.has_dynamic_imports = True
            else:
                self.has_dynamic_imports = True
        else:
            if node.module:
                base = node.module
                for alias in node.names:
                    self.dependencies.add(f"{base}.{alias.name}")
                    self.dependencies.add(base)
            else:
                self.has_dynamic_imports = True

        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in ('__import__', 'eval', 'exec'):
                self.has_dynamic_imports = True
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr == 'import_module':
                self.has_dynamic_imports = True
        self.generic_visit(node)

def get_module_name(file_path: Path, repo_root: Path) -> str:
    try:
        rel_path = file_path.relative_to(repo_root)
    except ValueError:
        return ""
    if rel_path.name == "__init__.py":
        return str(rel_path.parent).replace(os.sep, ".")
    if rel_path.suffix == ".py":
        return str(rel_path.with_suffix("")).replace(os.sep, ".")
    return str(rel_path)

def extract_dart_deps(file_path: Path, repo_root: Path) -> Tuple[Set[str], bool]:
    script_path = repo_root / "tools" / "change_impact" / "parse_dart.dart"
    if not script_path.exists():
        return set(), False

    try:
        result = subprocess.run(
            ["dart", "run", str(script_path), str(file_path)],
            capture_output=True,
            text=True,
            cwd=repo_root
        )
        if result.returncode != 0:
            if "Could not resolve the package 'analyzer'" in result.stderr or "Not found: 'package:analyzer" in result.stderr or "Couldn't resolve the package 'analyzer'" in result.stderr:
                raise Exception("BLOCKED: Missing parser capability")
            # Other errors like syntax error
            return set(), True

        output = result.stdout.strip()
        if output:
            try:
                data = json.loads(output)
                return set(data.get("deps", [])), data.get("dynamic", False)
            except json.JSONDecodeError:
                return set(), True
        return set(), False
    except FileNotFoundError:
        # dart not found
        raise Exception("BLOCKED: Missing parser capability")

def analyze_impact(repo_root: Path, changed_files: List[str]) -> Dict[str, Set[str]]:
    if not os.access(repo_root, os.R_OK):
        raise PermissionError("Repository access is unavailable")

    all_files = []
    tests = set()
    for root, dirs, files in os.walk(repo_root):
        if ".git" in root:
            continue
        for file in files:
            if file.endswith(".py") or file.endswith(".dart"):
                fpath = Path(root) / file
                all_files.append(fpath)
                if (file.startswith("test_") and file.endswith(".py")) or (file.endswith("_test.dart")):
                    try:
                        tests.add(str(fpath.relative_to(repo_root)))
                    except ValueError:
                        pass

    module_to_file = {}
    for f in all_files:
        if f.suffix == ".py":
            mod = get_module_name(f, repo_root)
            if mod:
                module_to_file[mod] = str(f.relative_to(repo_root))

    file_to_deps = {}
    uncertain_files = set()

    for f in all_files:
        try:
            rel = str(f.relative_to(repo_root))
        except ValueError:
            continue

        deps = set()
        is_dynamic = False

        if f.suffix == ".py":
            try:
                with open(f, "r", encoding="utf-8") as file_obj:
                    content = file_obj.read()
                tree = ast.parse(content, filename=str(f))
                mod = get_module_name(f, repo_root)
                visitor = DependencyVisitor(mod)
                visitor.visit(tree)

                for d in visitor.dependencies:
                    if d in module_to_file:
                        deps.add(module_to_file[d])
                    else:
                        parts = d.split(".")
                        for i in range(len(parts), 0, -1):
                            prefix = ".".join(parts[:i])
                            if prefix in module_to_file:
                                deps.add(module_to_file[prefix])
                                break

                if visitor.has_dynamic_imports:
                    is_dynamic = True
            except SyntaxError:
                is_dynamic = True
            except Exception:
                is_dynamic = True
        elif f.suffix == ".dart":
            try:
                dart_deps, d_dynamic = extract_dart_deps(f, repo_root)
                for d in dart_deps:
                    if d.startswith("dart:"):
                        continue
                    if d.startswith("package:"):
                        parts = d.replace("package:", "").split("/", 1)
                        if len(parts) == 2:
                            pkg, path = parts
                            # Map to lib directory as a standard Dart convention
                            lib_path = Path("lib") / path
                            deps.add(str(lib_path))
                            # Also map directly in case package root is repo root
                            deps.add(path)
                    else:
                        try:
                            # relative to current file's parent
                            resolved = (f.parent / d).resolve()
                            deps.add(str(resolved.relative_to(repo_root)))
                        except (ValueError, FileNotFoundError, RuntimeError):
                            pass
                if d_dynamic:
                    is_dynamic = True
            except Exception as e:
                if str(e) == "BLOCKED: Missing parser capability":
                    raise
                is_dynamic = True

        file_to_deps[rel] = deps
        if is_dynamic:
            uncertain_files.add(rel)

    reverse_graph = {f: set() for f in file_to_deps.keys()}
    for f, deps in file_to_deps.items():
        for d in deps:
            if d in reverse_graph:
                reverse_graph[d].add(f)

    affected = set()
    queue = []

    for ch in changed_files:
        ch_path = Path(ch)
        if ch_path.is_absolute():
            try:
                ch = str(ch_path.relative_to(repo_root))
            except ValueError:
                pass
        affected.add(ch)
        queue.append(ch)

    while queue:
        curr = queue.pop(0)
        if curr in reverse_graph:
            for nxt in reverse_graph[curr]:
                if nxt not in affected:
                    affected.add(nxt)
                    queue.append(nxt)

    has_uncertainty = any(a in uncertain_files for a in affected)

    affected_tests = set()
    if has_uncertainty:
        affected_tests = tests
    else:
        for a in affected:
            if a in tests:
                affected_tests.add(a)

    return {
        "affected_files": affected,
        "affected_tests": affected_tests
    }
