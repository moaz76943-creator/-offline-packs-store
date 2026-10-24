import sys
import json
from pathlib import Path
from tools.change_impact.engine import build_dependency_graph, find_all_tests, compute_impact

def main():
    changed_files = sys.argv[1:]

    if not changed_files:
        print(json.dumps({"affected_files": [], "affected_tests": []}))
        return

    root_dir = Path.cwd()

    graph, dynamic_status = build_dependency_graph(root_dir)
    all_tests = find_all_tests(root_dir)

    affected_files, affected_tests = compute_impact(graph, dynamic_status, changed_files, all_tests)

    print(json.dumps({
        "affected_files": sorted(affected_files),
        "affected_tests": sorted(affected_tests)
    }, indent=2))

if __name__ == '__main__':
    main()
