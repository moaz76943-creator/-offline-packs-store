import argparse
import json
import sys
from pathlib import Path
from tools.change_impact.engine import ChangeImpactEngine

def main():
    parser = argparse.ArgumentParser(description="AST-Based Change Impact & Test Selection Engine")
    parser.add_argument('--repo-root', type=str, default='.', help="Repository root directory")
    parser.add_argument('changed_files', nargs='*', help="List of changed files to analyze")

    args = parser.parse_args()

    if not args.changed_files:
        # Read from stdin if not provided as arguments (useful for pipes)
        if not sys.stdin.isatty():
            changed_files = [line.strip() for line in sys.stdin if line.strip()]
        else:
            changed_files = []
    else:
        changed_files = args.changed_files

    if not changed_files:
        print(json.dumps({'affected_files': [], 'impacted_tests': [], 'uncertain': False}))
        return

    try:
        engine = ChangeImpactEngine(args.repo_root)
        engine.build_graph()
        result = engine.analyze_impact(changed_files)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({'error': str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
