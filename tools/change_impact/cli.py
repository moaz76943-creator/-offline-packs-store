import argparse
import json
import sys
from engine import DependencyEngine

def main():
    parser = argparse.ArgumentParser(description="AST-Based Change Impact Engine")
    parser.add_argument("--root", required=True, help="Root directory of the repository")
    parser.add_argument("--manifest", required=True, help="Path to the tests manifest JSON file")
    parser.add_argument("--changed-files", nargs="+", default=[], help="List of changed file paths relative to root")

    args = parser.parse_args()

    try:
        engine = DependencyEngine(args.root)
        engine.load_manifest(args.manifest)
        engine.build_graph()

        impacted_tests, impacted_files = engine.get_impacted_tests(args.changed_files)

        print(json.dumps({
            "impacted_files": sorted(list(impacted_files)),
            "impacted_tests": sorted(list(impacted_tests)),
            "dynamic_imports_detected": engine.dynamic_imports_detected,
        }))

    except RuntimeError as e:
        if "BLOCKED" in str(e):
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        else:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
