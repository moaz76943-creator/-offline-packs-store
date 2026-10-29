import json
import os
import sys

from tools.change_impact.engine import DependencyEngine

def main():
    if not os.access(os.getcwd(), os.R_OK):
        print("BLOCKED: Missing repository access")
        sys.exit(1)

    # changed files can be passed via sys.argv[1:]
    changed_files = sys.argv[1:]
    if not changed_files:
        print(json.dumps({"affected_files": [], "affected_tests": []}))
        return

    engine = DependencyEngine(os.getcwd())
    engine.build_graph()

    affected_files, affected_tests = engine.get_impact(changed_files)

    output = {
        "affected_files": affected_files,
        "affected_tests": affected_tests
    }

    print(json.dumps(output, indent=2))

if __name__ == '__main__':
    main()
