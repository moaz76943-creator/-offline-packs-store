import sys
import os
import json
from .engine import ChangeImpactEngine

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m tools.change_impact <changed_file1> [changed_file2 ...]")
        sys.exit(1)

    repo_root = os.getcwd()
    changed_files = sys.argv[1:]

    engine = ChangeImpactEngine(repo_root)
    engine.analyze()

    impacted, tests = engine.get_impacted_tests(changed_files)

    output = {
        "changed": sorted(list(changed_files)),
        "impacted": sorted(list(impacted)),
        "tests": sorted(list(tests))
    }

    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    main()
