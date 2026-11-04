import sys
import os
import json
from pathlib import Path

# Add repo root to sys.path to allow imports from tools
def install_repo_import_path():
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root

repo_root = install_repo_import_path()

from tools.change_impact.engine import ChangeImpactEngine, ParserBlockedError

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m tools.change_impact <changed_files...>")
        sys.exit(1)

    changed_files = sys.argv[1:]

    # Verify workspace authorization using os.access(repo_root, os.R_OK | os.X_OK) failing closed if not accessible.
    if not os.access(repo_root, os.R_OK | os.X_OK):
        print("UNAUTHORIZED_WORKSPACE: Cannot access repository root.")
        sys.exit(1)

    engine = ChangeImpactEngine(str(repo_root))
    try:
        affected_files, impacted_tests = engine.analyze(changed_files)
        result = {
            "affected_files": affected_files,
            "impacted_tests": impacted_tests
        }
        print(json.dumps(result, indent=2))
    except ParserBlockedError as e:
        # The engine will already print the required message
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
