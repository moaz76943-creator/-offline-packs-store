"""Collect read-only GitHub task evidence into immutable local reports."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from .verifier import EvidenceError, GhReader, verify, markdown


def _persist(directory, data, suffix):
    raw = data.encode('utf-8')
    target = directory / (hashlib.sha256(raw).hexdigest() + suffix)
    if target.is_symlink():
        raise EvidenceError('UNSAFE_OUTPUT_LINK')
    if target.exists():
        if target.read_bytes() != raw:
            raise EvidenceError('IMMUTABLE_REPORT_COLLISION')
        return target
    fd, name = tempfile.mkstemp(prefix='.evidence-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if hasattr(os, 'link'):
            try:
                os.link(name, target)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != raw:
                    raise EvidenceError('IMMUTABLE_REPORT_COLLISION')
        else:
            if target.exists():
                if target.is_symlink() or target.read_bytes() != raw:
                    raise EvidenceError('IMMUTABLE_REPORT_COLLISION')
            else:
                os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--pr', required=True, type=int)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--verify-artifacts', action='store_true')
    parser.add_argument('--private-url', action='append', default=[])
    args = parser.parse_args(argv)
    try:
        report = verify(GhReader(), args.repo, args.pr, args.task_id, args.owner,
                        verify_artifacts=args.verify_artifacts,
                        private_links=args.private_url)
        directory = args.output_dir
        if directory.is_symlink():
            raise EvidenceError('UNSAFE_OUTPUT_DIRECTORY')
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise EvidenceError('UNSAFE_OUTPUT_DIRECTORY')
        json_file = _persist(directory,
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n', '.json')
        md_file = _persist(directory, markdown(report), '.md')
        print(json.dumps({'final_status': report['final_status'],
                          'json_report': str(json_file), 'markdown_report': str(md_file)}))
        return 0 if report['final_status'] == 'VERIFIED' else 2
    except (EvidenceError, OSError) as exc:
        print(json.dumps({'final_status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
