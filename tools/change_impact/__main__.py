import sys
import os
import json
from tools.change_impact.engine import ImpactEngine

def main():
    repo_root = os.getcwd()

    # Check Directory Constraints & Security
    if not os.access(repo_root, os.R_OK | os.X_OK):
        print("BLOCKED: Missing repository access", file=sys.stderr)
        sys.exit(1)

    changed_files = sys.argv[1:]
    if not changed_files:
        # No files changed, output empty
        print(json.dumps({"impacted_files": [], "impacted_tests": []}))
        return

    engine = ImpactEngine(repo_root)
    engine.scan_directory()

    impacted_files, impacted_tests = engine.get_impacted_tests(changed_files)

    result = {
        "impacted_files": sorted(list(impacted_files)),
        "impacted_tests": sorted(list(impacted_tests))
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()
