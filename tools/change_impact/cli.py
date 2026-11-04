import argparse
import json
import sys
import os
from pathlib import Path

# Add repo root to PYTHONPATH to allow absolute imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.change_impact.engine import DependencyEngine

def main():
    parser = argparse.ArgumentParser(description="AST-Based Change Impact & Test Selection Engine")
    parser.add_argument('--repo-root', type=str, default='.', help='Root of the repository')
    parser.add_argument('--changed-files', type=str, required=True, help='Comma-separated list of changed files')
    parser.add_argument('--output', type=str, help='Path to output JSON result')

    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    changed_files = [f.strip() for f in args.changed_files.split(',') if f.strip()]

    try:
        engine = DependencyEngine(str(repo_root))
    except PermissionError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(1)

    # Find all source files for full graph construction
    source_files = []
    for root, _, files in os.walk(repo_root):
        if '.git' in root or 'node_modules' in root or '.dart_tool' in root:
            continue
        for file in files:
            if file.endswith('.py') or file.endswith('.dart'):
                source_files.append(Path(root) / file)

    try:
        graph = engine.build_graph(source_files)
        impact = engine.determine_impact(changed_files, graph)

        result = {
            'graph': graph,
            'impacted_files': impact['impacted_files'],
            'test_ids': impact['test_ids'],
            'uncertain': impact['uncertain']
        }

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
        else:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error during analysis: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
