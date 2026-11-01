import sys
import json
from pathlib import Path
from engine import DependencyEngine

def main():
    if len(sys.argv) < 3:
        print(json.dumps({'error': 'Usage: cli.py <repo_root> <changed_file1> ...'}))
        sys.exit(1)

    repo_root = Path(sys.argv[1]).resolve()
    changed_files = sys.argv[2:]

    try:
        engine = DependencyEngine(repo_root)

        # Build graph for all relevant files in repo
        for ext in ("*.py", "*.dart"):
            for filepath in repo_root.rglob(ext):
                # skip ignored dirs like .git, .dart_tool
                if ".git" in filepath.parts or ".dart_tool" in filepath.parts:
                    continue
                if filepath.suffix == ".py":
                    engine.parse_python_file(filepath)
                elif filepath.suffix == ".dart":
                    engine.parse_dart_file(filepath)

        engine.build_graph()

        # Normalize changed files
        normalized_changes = []
        for f in changed_files:
            p = Path(f)
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            try:
                rel = p.relative_to(repo_root)
                normalized_changes.append(str(rel))
            except ValueError:
                pass

        impacted = engine.calculate_impact(normalized_changes)

        # tests: basic heuristic
        tests = set()
        for i in impacted:
            p = Path(i)
            if p.suffix == ".py":
                # if it starts with test_, it's a test
                if p.name.startswith("test_"):
                    tests.add(i)
                else:
                    # Look for test_NAME.py in same dir
                    test_file = p.parent / f"test_{p.name}"
                    if (repo_root / test_file).exists():
                        tests.add(str(test_file))
            elif p.suffix == ".dart":
                if p.name.endswith("_test.dart"):
                    tests.add(i)
                else:
                    test_file = p.parent / f"{p.stem}_test.dart"
                    if (repo_root / test_file).exists():
                        tests.add(str(test_file))

        print(json.dumps({
            'impacted_files': sorted(list(impacted)),
            'impacted_tests': sorted(list(tests))
        }))
    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
