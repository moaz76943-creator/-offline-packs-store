import sys
import json
from pathlib import Path
from tools.change_impact.engine import analyze_impact

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"affected_files": [], "affected_tests": []}))
        sys.exit(0)

    changed_files = sys.argv[1:]
    repo_root = Path.cwd()

    try:
        impact = analyze_impact(repo_root, changed_files)
        print(json.dumps({
            "affected_files": sorted(list(impact.get("affected_files", set()))),
            "affected_tests": sorted(list(impact.get("affected_tests", set())))
        }))
    except Exception as e:
        if str(e) == "BLOCKED: Missing parser capability":
            print("BLOCKED: Missing parser capability")
            sys.exit(1)
        raise

if __name__ == "__main__":
    main()
