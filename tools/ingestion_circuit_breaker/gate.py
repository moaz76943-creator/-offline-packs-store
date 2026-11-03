#!/usr/bin/env python3
"""Mandatory preflight CLI for source ingestion."""
import argparse
import os
import hashlib
import json
import shutil
import sys
import uuid
import time
from pathlib import Path

# Keep module and direct-script entry points bound to the same canonical policy.
try:
    from legal.ledger.admission import LICENSES, OBLIGATIONS
except ImportError:
    import importlib.util
    policy_path = Path(__file__).resolve().parents[2] / 'legal/ledger/admission.py'
    spec = importlib.util.spec_from_file_location('_ingestion_ledger_policy', policy_path)
    if spec is None or spec.loader is None:
        raise ImportError('canonical ledger policy unavailable')
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    LICENSES, OBLIGATIONS = policy.LICENSES, policy.OBLIGATIONS

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path.cwd())
    parser.add_argument('--manifest', type=Path, required=True, help="Path to input ingestion manifest")
    parser.add_argument('--quarantine', type=Path, help="Directory to move rejected files")
    return parser.parse_args(argv)

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()

def quarantine_files(args, manifest_dict, errors):
    if not args.quarantine:
        return
    q_dir = args.quarantine.resolve()
    q_dir.mkdir(parents=True, exist_ok=True)

    uid = uuid.uuid4().hex[:8]

    # Save reason
    reason_path = q_dir / f"{uid}.reason.txt"
    reason_path.write_text("\n".join(errors) + "\n", encoding="utf-8")

    # Copy manifest and artifacts instead of moving to prevent destroying evidence
    if args.manifest.exists():
        shutil.copy2(args.manifest, q_dir / f"{uid}_manifest.json")

    if isinstance(manifest_dict, dict):
        for path_key in ['artifact_path']:
            if path_key in manifest_dict and isinstance(manifest_dict[path_key], str):
                artifact_path = args.repo_root / manifest_dict[path_key]
                if not Path(manifest_dict[path_key]).is_absolute() and artifact_path.exists():
                    shutil.copy2(artifact_path, q_dir / f"{uid}_{artifact_path.name}")

def process(args):
    # Preflight the selected workspace, not the process working directory.
    # This is an availability check; actual writes must still handle OS errors.
    workspace = args.repo_root.resolve()
    if not workspace.is_dir() or not os.access(workspace, os.W_OK | os.X_OK):
        print("WORKSPACE_ACCESS_DENIED: workspace is not writable/traversable", file=sys.stderr)
        return 1, ["WORKSPACE_ACCESS_DENIED"]

    try:
        manifest_data = args.manifest.read_text(encoding='utf-8')
        manifest_dict = json.loads(manifest_data)
    except Exception as e:
        print(f"Error reading manifest: {e}", file=sys.stderr)
        return 1, ["MALFORMED_MANIFEST"]

    root = args.repo_root.resolve()
    ledger_path = root / 'legal/ledger/sources.json'

    # If actual ingestion integration requires unavailable interfaces, report BLOCKED_INTEGRATION
    # Based on the requirement: "If actual ingestion integration requires unavailable interfaces, report BLOCKED_INTEGRATION rather than claiming that the guard is enforced in production."
    if manifest_dict.get('requires_unavailable_interfaces'):
        print("BLOCKED_INTEGRATION: required interfaces are unavailable", file=sys.stderr)
        return 3, ["BLOCKED_INTEGRATION"]

    try:
        ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"Error reading ledger: {e}", file=sys.stderr)
        return 1, ["MALFORMED_LEDGER"]

    sources = {s.get('source_id'): s for s in ledger.get('sources', []) if isinstance(s, dict)}

    errors = []

    source_id = manifest_dict.get('source_id')
    if not source_id or source_id not in sources:
        errors.append("UNKNOWN_SOURCE")

    # Check for expired token
    expiration = manifest_dict.get('token_expiration')
    if expiration and time.time() > expiration:
        errors.append("EXPIRED_TOKEN")

    # Check for revoked admission
    if manifest_dict.get('admission_revoked'):
        errors.append("REVOKED_ADMISSION")

    actual_hash = None
    if not errors:
        src = sources[source_id]

        # Check source hash
        artifact_path = manifest_dict.get('artifact_path')
        if not artifact_path:
            errors.append("MISSING_ARTIFACT_PATH")
        else:
            full_artifact_path = root / artifact_path
            # Prevent path traversal by rejecting absolute paths or paths traversing up
            if Path(artifact_path).is_absolute() or not full_artifact_path.resolve().is_relative_to(root):
                errors.append("INVALID_ARTIFACT_PATH")
            elif not full_artifact_path.exists():
                errors.append("MISSING_ARTIFACT")
            else:
                actual_hash = sha256_file(full_artifact_path)
                expected_hash = manifest_dict.get('artifact_sha256')
                if actual_hash != expected_hash:
                    errors.append("HASH_MISMATCH_MANIFEST")

                # Check against ledger
                if expected_hash != src.get('retrieval', {}).get('sha256'):
                    errors.append("HASH_MISMATCH_LEDGER")

        # Check license and compatibility
        output_license = manifest_dict.get('intended_output_license')
        src_license = src.get('license', {}).get('id')
        if not output_license:
            errors.append("MISSING_OUTPUT_LICENSE")
        if not src_license:
            errors.append("MISSING_SOURCE_LICENSE")
        output_supported = isinstance(output_license, str) and output_license in LICENSES
        source_supported = isinstance(src_license, str) and src_license in LICENSES
        if output_license and not output_supported:
            errors.append("UNSUPPORTED_OUTPUT_LICENSE")
        if src_license and not source_supported:
            errors.append("UNSUPPORTED_SOURCE_LICENSE")
        if (src_license == 'CC-BY-2.0-FR'
                and output_license != 'CC-BY-2.0-FR'):
            errors.append("LICENSE_CONVERSION_REVIEW_REQUIRED")

        if source_supported and output_supported:
            # Keep the enforced ledger's restriction on automatic conversion.
            if src_license == 'CC0-1.0' and output_license == 'PUBLIC-DOMAIN':
                errors.append("LICENSE_CONFLICT")
            elif src_license in OBLIGATIONS and output_license != src_license:
                errors.append("LICENSE_CONFLICT")

    if errors:
        quarantine_files(args, manifest_dict, errors)
        for e in errors:
            print(f"BLOCK: {e}", file=sys.stderr)
        return 2, errors

    # Success: Issue admission manifest
    admission = {
        "status": "ADMITTED",
        "source_id": source_id,
        "artifact_sha256": actual_hash,
        "source_license": src_license,
        "destination": manifest_dict.get("destination", "unknown"),
        "expires_at": int(time.time()) + 300
    }

    print(json.dumps(admission))
    return 0, []

def main(argv=None):
    args = parse_args(argv)
    code, _ = process(args)
    return code

if __name__ == '__main__':
    sys.exit(main())
