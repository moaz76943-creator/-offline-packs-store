import sys
import json
import os
from .engine import DependencyEngine

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python -m tools.change_impact <changed_file1> <changed_file2> ..."}))
        sys.exit(1)

    changed_files = sys.argv[1:]

    # In a real environment we are likely running from the repo root
    # or we can discover it by finding '.git' or assuming we are run from root
    # We will assume current working directory is repo root if no other context.
    # We could also use the path of this file to determine root.
    repo_root = os.getcwd()

    try:
        engine = DependencyEngine(repo_root)
        engine.scan_tree()
        impact = engine.map_impact(changed_files)
        print(json.dumps(impact, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
