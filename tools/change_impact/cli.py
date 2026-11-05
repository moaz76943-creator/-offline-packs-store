import argparse
import json
import sys
import os
from engine import ChangeImpactEngine

def main():
    parser = argparse.ArgumentParser(description="AST-Based Change Impact & Test Selection Engine")
    parser.add_argument('files', nargs='+', help='List of changed files')
    parser.add_argument('--repo-root', default='.', help='Repository root directory')
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)

    try:
        engine = ChangeImpactEngine(repo_root)
        result = engine.analyze_impact(args.files)

        if result.get('error'):
            print(json.dumps({'error': result['error']}))
            sys.exit(1)

        print(json.dumps({
            'impacted_files': result['impacted_files'],
            'impacted_tests': result['impacted_tests'],
            'uncertain_files': result['uncertain_files']
        }, indent=2))

    except Exception as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
