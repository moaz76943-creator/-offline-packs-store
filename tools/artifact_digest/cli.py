import argparse
import sys
import json
import os
from pathlib import Path

def install_repo_import_path():
    """Ensure the repository root is in sys.path for direct execution."""
    # Find the repository root by going up until we find something like 'tools'
    current_dir = Path(__file__).resolve().parent
    repo_root = current_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

install_repo_import_path()

from tools.artifact_digest.engine import compute_sha256, build_digest_index, compare_indexes

def main():
    parser = argparse.ArgumentParser(description="Content-Addressed Artifact Digest & Provenance Engine CLI")
    subparsers = parser.add_subparsers(dest='command', required=True)

    # hash subcommand
    hash_parser = subparsers.add_parser('hash', help='Compute SHA-256 hash of a file')
    hash_parser.add_argument('file', help='Path to the file to hash')

    # index subcommand
    index_parser = subparsers.add_parser('index', help='Build a deterministic artifact digest index')
    index_parser.add_argument('--base-dir', default='.', help='Base directory for resolving paths')
    index_parser.add_argument('--manifest', required=True, help='Path to input manifest JSON (list of records)')
    index_parser.add_argument('--out', required=True, help='Path to output index JSON file')

    # compare subcommand
    compare_parser = subparsers.add_parser('compare', help='Compare two indexes')
    compare_parser.add_argument('--old', required=True, help='Path to old index JSON file')
    compare_parser.add_argument('--new', required=True, help='Path to new index JSON file')
    compare_parser.add_argument('--out', help='Path to output change events JSON file (optional)')

    args = parser.parse_args()

    if args.command == 'hash':
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        print(compute_sha256(args.file))

    elif args.command == 'index':
        if not os.path.exists(args.manifest):
            print(f"Error: Manifest not found: {args.manifest}", file=sys.stderr)
            sys.exit(1)
        with open(args.manifest, 'r', encoding='utf-8') as f:
            records = json.load(f)
        if not isinstance(records, list):
            print("Error: Manifest should contain a list of artifact records.", file=sys.stderr)
            sys.exit(1)

        build_digest_index(args.base_dir, records, args.out)
        print(f"Index built successfully at {args.out}")

    elif args.command == 'compare':
        if not os.path.exists(args.old):
            print(f"Error: Old index not found: {args.old}", file=sys.stderr)
            sys.exit(1)
        if not os.path.exists(args.new):
            print(f"Error: New index not found: {args.new}", file=sys.stderr)
            sys.exit(1)

        with open(args.old, 'r', encoding='utf-8') as f:
            old_index = json.load(f)
        with open(args.new, 'r', encoding='utf-8') as f:
            new_index = json.load(f)

        events = compare_indexes(old_index, new_index)
        output = json.dumps(events, indent=2, sort_keys=True)
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"Events written to {args.out}")
        else:
            print(output)

if __name__ == '__main__':
    main()
