import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Any
from tools.change_impact.python_parser import parse_python_file

DART_SCRIPT = Path(__file__).parent / 'dart_parser.dart'

def run_dart_parser(filepath: str) -> Dict[str, Any]:
    if not DART_SCRIPT.exists():
        print("BLOCKED: Missing parser capability")
        sys.exit(1)

    try:
        subprocess.run(["dart", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("BLOCKED: Missing parser capability")
        sys.exit(1)

    script_dir = DART_SCRIPT.parent
    if not (script_dir / '.dart_tool' / 'package_config.json').exists():
         try:
             subprocess.run(["dart", "pub", "get"], cwd=str(script_dir), capture_output=True, check=True)
         except subprocess.CalledProcessError:
             print("BLOCKED: Failed to fetch dart dependencies")
             sys.exit(1)

    try:
        result = subprocess.run(
            ["dart", "run", str(DART_SCRIPT), filepath],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(script_dir)
        )
        output = result.stdout.strip()
        if output.startswith("BLOCKED:"):
            print(output)
            sys.exit(1)
        return json.loads(output)
    except subprocess.CalledProcessError as e:
        if "BLOCKED:" in e.stdout:
            print(e.stdout.strip())
            sys.exit(1)
        print("BLOCKED: Parser crash")
        sys.exit(1)
    except json.JSONDecodeError:
        print("BLOCKED: Bad output from parser")
        sys.exit(1)

def resolve_python_path(base_dir: Path, source_file: Path, module_ref: str) -> str:
    if module_ref.startswith('.'):
        level = 0
        while module_ref.startswith('.'):
            level += 1
            module_ref = module_ref[1:]

        target_dir = source_file.parent
        for _ in range(level - 1):
            target_dir = target_dir.parent

        if not module_ref:
            pass
        else:
            parts = module_ref.split('.')
            target_path = target_dir.joinpath(*parts)

            if target_path.with_suffix('.py').exists():
                return str(target_path.with_suffix('.py').relative_to(base_dir))
            if (target_path / '__init__.py').exists():
                return str((target_path / '__init__.py').relative_to(base_dir))

    else:
        parts = module_ref.split('.')
        target_path = base_dir.joinpath(*parts)
        if target_path.with_suffix('.py').exists():
            return str(target_path.with_suffix('.py').relative_to(base_dir))
        if (target_path / '__init__.py').exists():
            return str((target_path / '__init__.py').relative_to(base_dir))

    return ""

def get_dart_package_name(base_dir: Path) -> str:
    pubspec = base_dir / 'pubspec.yaml'
    if pubspec.exists():
        try:
            with open(pubspec, 'r') as f:
                for line in f:
                    if line.startswith('name:'):
                        return line.split(':')[1].strip()
        except Exception:
            return ""
    return ""

def resolve_dart_path(base_dir: Path, source_file: Path, uri: str) -> str:
    if uri.startswith('package:'):
        pkg_uri = uri[len('package:'):]
        parts = pkg_uri.split('/')
        if not parts: return ""

        pkg_name = parts[0]
        root_pkg_name = get_dart_package_name(base_dir)

        if pkg_name == root_pkg_name:
            target_path = base_dir / 'lib' / '/'.join(parts[1:])
            if target_path.exists():
                return str(target_path.relative_to(base_dir))
        return ""
    else:
        target_path = (source_file.parent / uri).resolve()
        try:
            return str(target_path.relative_to(base_dir))
        except ValueError:
            return ""

def build_dependency_graph(root_dir: Path) -> tuple[Dict[str, List[str]], Dict[str, bool]]:
    graph: Dict[str, List[str]] = {}
    dynamic_status: Dict[str, bool] = {}

    for root, _, files in os.walk(root_dir):
        if '.git' in root or '.dart_tool' in root:
            continue

        for file in files:
            filepath = Path(root) / file
            try:
                rel_path = str(filepath.relative_to(root_dir))
            except ValueError:
                continue

            if file.endswith('.py'):
                info = parse_python_file(str(filepath))
                dynamic_status[rel_path] = info.get('dynamic_imports', False)
                for dep in info.get('dependencies', []):
                    resolved = resolve_python_path(root_dir, filepath, dep)
                    if resolved:
                        graph.setdefault(resolved, []).append(rel_path)
            elif file.endswith('.dart'):
                info = run_dart_parser(str(filepath))
                dynamic_status[rel_path] = info.get('dynamic_imports', False)
                for dep in info.get('dependencies', []):
                    resolved = resolve_dart_path(root_dir, filepath, dep)
                    if resolved:
                        graph.setdefault(resolved, []).append(rel_path)

    return graph, dynamic_status

def find_all_tests(root_dir: Path) -> List[str]:
    tests = []
    for root, _, files in os.walk(root_dir):
        if '.git' in root or '.dart_tool' in root:
            continue
        for file in files:
            if file.startswith('test_') and file.endswith('.py'):
                try:
                    tests.append(str(Path(root).joinpath(file).relative_to(root_dir)))
                except ValueError:
                    pass
            elif file.endswith('_test.dart'):
                try:
                    tests.append(str(Path(root).joinpath(file).relative_to(root_dir)))
                except ValueError:
                    pass
    return tests

def compute_impact(graph: Dict[str, List[str]], dynamic_status: Dict[str, bool], changed_files: List[str], all_tests: List[str]) -> tuple[List[str], List[str]]:
    visited = set(changed_files)
    queue = list(changed_files)

    while queue:
        current = queue.pop(0)

        if dynamic_status.get(current, False):
            return list(visited), all_tests

        for dependant in graph.get(current, []):
            if dependant not in visited:
                visited.add(dependant)
                queue.append(dependant)

    impacted_tests = [f for f in visited if f in all_tests]
    return list(visited), impacted_tests
