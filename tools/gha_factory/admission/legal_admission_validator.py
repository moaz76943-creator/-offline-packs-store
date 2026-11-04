#!/usr/bin/env python3
"""Compatibility entry point for the canonical, fail-closed rights gate.

This command cannot approve a source. A positional ledger path is retained for
old callers; all validation and exit statuses belong to legal.ledger.admission.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from legal.ledger import admission


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and not args[0].startswith('-'):
        args[:1] = ['--ledger', args[0]]
    if not any(arg == '--repo-root' or arg.startswith('--repo-root=')
               for arg in args):
        args.extend(['--repo-root', str(ROOT)])
    return admission.main(args)


def audit_sources_ledger(filepath):
    return main(['--ledger', str(filepath)]) == 0


if __name__ == '__main__':
    sys.exit(main())
