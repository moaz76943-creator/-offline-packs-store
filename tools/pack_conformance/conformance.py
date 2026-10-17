import argparse
import sys
from pathlib import Path

# Note: The logic in gha_factory.pack_conformance.check already implements
# all the complex requirements (FTS5 verification against SQLite tables directly,
# schema projection including POS validation from jsonschema, and NFKC sort_key).
from tools.gha_factory.pack_conformance import check

def check_conformance(archive, language, root, expected_sha256=None):
    try:
        # We wrap the existing strict audit in our requested interface.
        result = check.inspect(archive, language, root=root, allow_fixture=True, expected_sha256=expected_sha256)
        return result
    except check.ConformanceError as exc:
        if exc.code == 'PROVENANCE_MISSING':
            # Requested: Provide explicit unverified status for absent source evidence.
            return {"status": "UNVERIFIED", "reason": str(exc), "error_code": exc.code}
        return {"status": "FAIL", "reason": str(exc), "error_code": exc.code}
    except Exception as exc:
        return {"status": "FAIL", "reason": str(exc), "error_code": "UNKNOWN_FAILURE"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Strict conformance test suite for public multilingual SQLite v2 content packs and search indexes.")
    ap.add_argument('--root', type=Path, default=Path('.'), help="Repository root path")
    ap.add_argument('--archive', type=Path, required=True, help="Path to the pack archive")
    ap.add_argument('--language', required=True, help="Target language code")
    ap.add_argument('--sha256', help="Expected SHA-256 of the archive")
    args = ap.parse_args(argv)

    try:
        archive_bytes = args.archive.read_bytes()
    except OSError as exc:
        print(f'{{"status": "FAIL", "reason": "Failed to read archive: {exc}"}}')
        return 1

    result = check_conformance(archive_bytes, args.language, args.root, args.sha256)

    import json
    print(json.dumps(result, separators=(',', ':')))

    if result.get('status') in ('FAIL', 'UNVERIFIED'):
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
