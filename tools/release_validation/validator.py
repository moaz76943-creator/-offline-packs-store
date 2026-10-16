#!/usr/bin/env python3
"""Executable Public Release Eligibility Gate"""
import argparse
import json
import sys
import tempfile
import os
from pathlib import Path

try:
    from legal.ledger.admission import LICENSES, sha256_file
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from legal.ledger.admission import LICENSES, sha256_file

def validate_artifact(artifact, repo_root):
    reasons = []
    auth = artifact.get('repository_authorization')
    if not auth or auth != 'VERIFIED_FOR_AUTHORIZED_HANDOFF':
        reasons.append('UNAUTHORIZED_REPOSITORY')


    art_id = artifact.get('id')
    if not art_id:
        reasons.append("MISSING_IDENTITY")

    path_str = artifact.get('path')
    if not path_str:
        reasons.append("MISSING_PATH")
    else:
        full_path = (repo_root / path_str).resolve()

        try:
            full_path.relative_to(repo_root.resolve())
        except ValueError:
            reasons.append("PATH_TRAVERSAL_DETECTED")

        if not full_path.is_file():
            reasons.append("FILE_NOT_FOUND")
        else:
            expected_hash = artifact.get('sha256')
            if not expected_hash:
                reasons.append("MISSING_HASH")
            else:
                actual_hash = sha256_file(full_path)
                if actual_hash != expected_hash:
                    reasons.append("HASH_MISMATCH")

    license_val = artifact.get('license')
    if not license_val:
        reasons.append("MISSING_LICENSE")
    elif license_val not in LICENSES:
        reasons.append("UNAPPROVED_LICENSE")

    validations = artifact.get('validations', {})

    for check in ['schema_conformance', 'format_conformance', 'provenance_evidence', 'attribution_evidence']:
        status = validations.get(check)
        if status is None:
            reasons.append(f"{check.upper()}_NOT_RUN")
        elif status != 'PASSED':
            reasons.append(f"{check.upper()}_{status}")

    return reasons

def evaluate_candidates(candidates_path, repo_root, output_path):
    if not candidates_path.is_file():
        return 1, {"error": "CANDIDATES_FILE_NOT_FOUND"}

    try:
        with open(candidates_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        return 1, {"error": "INVALID_JSON", "details": str(e)}

    artifacts = data.get('artifacts')
    if not isinstance(artifacts, list):
        return 1, {"error": "INVALID_FORMAT", "details": "artifacts must be a list"}

    approved = []
    all_passed = True
    report = {}

    for i, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            return 1, {"error": "INVALID_ARTIFACT_FORMAT"}

        art_id = artifact.get('id', f'unknown_{i}')
        reasons = validate_artifact(artifact, repo_root)

        if reasons:
            report[art_id] = reasons
            all_passed = False
        else:
            approved.append(artifact)
            report[art_id] = ["PASSED"]

    if not all_passed:
        return 1, report

    tmp_fd, tmp_path = tempfile.mkstemp(dir=output_path.parent, prefix="manifest_", suffix=".tmp", text=True)
    with os.fdopen(tmp_fd, 'w') as f:
        json.dump({
            "schema_version": "1.0.0",
            "approved_artifacts": approved
        }, f, indent=2)

    os.replace(tmp_path, output_path)

    return 0, report

def main(argv=None):
    parser = argparse.ArgumentParser(description="Executable Public Release Eligibility Gate")
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--candidates', type=Path, required=True, help="JSON file containing release candidates")
    parser.add_argument('--output', type=Path, required=True, help="Path to write the approved artifact manifest")

    args = parser.parse_args(argv)

    exit_code, report = evaluate_candidates(args.candidates, args.repo_root, args.output)

    print(json.dumps(report, indent=2))
    return exit_code

if __name__ == '__main__':
    sys.exit(main())
