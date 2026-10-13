#!/usr/bin/env python3
import hashlib
import json
import os
import sys
from pathlib import Path

LICENSES = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB reasonable limit

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()

def validate_contribution(manifest_dict, repo_root):
    # Expects a dictionary manifest.
    reasons = []
    status = "ACCEPT"
    receipt = None

    asset_path_str = manifest_dict.get('artifact_path')
    if not asset_path_str:
        return {"status": "REJECT", "reasons": ["Missing artifact_path"]}

    # Prevent path traversal
    if '..' in asset_path_str or asset_path_str.startswith('/'):
        return {"status": "REJECT", "reasons": ["Invalid path traversal in artifact_path"]}

    full_path = Path(repo_root) / asset_path_str
    try:
        resolved_path = full_path.resolve()
        if not resolved_path.is_relative_to(Path(repo_root).resolve()):
             return {"status": "REJECT", "reasons": ["Path outside repo"]}
    except Exception:
        pass

    if not full_path.exists():
        return {"status": "REJECT", "reasons": ["Artifact file does not exist"]}

    if full_path.stat().st_size > MAX_FILE_SIZE:
        return {"status": "REJECT", "reasons": ["Artifact size exceeds limit"]}

    expected_hash = manifest_dict.get('sha256')
    if not expected_hash:
        return {"status": "REJECT", "reasons": ["Missing sha256"]}

    actual_hash = sha256_file(full_path)
    if actual_hash != expected_hash:
        return {"status": "REJECT", "reasons": ["Hash mismatch"]}

    # License and Source checking
    source = manifest_dict.get('source_identity')
    if not source:
         return {"status": "REJECT", "reasons": ["Missing source_identity"]}

    if not manifest_dict.get('contributor_authorization'):
        status = "REVIEW_REQUIRED"
        reasons.append("Missing explicit contributor authorization evidence")

    license_id = manifest_dict.get('license_id')
    if license_id not in LICENSES:
        return {"status": "REJECT", "reasons": ["Unsupported or missing license"]}

    if license_id == 'CC0-1.0':
        evidence = manifest_dict.get('license_evidence')
        if not evidence or 'public domain' not in evidence.lower() and 'cc0' not in evidence.lower():
            return {"status": "REJECT", "reasons": ["False CC0 declaration: missing or inadequate explicit evidence"]}

    if license_id in ('CC-BY-SA-4.0', 'GFDL-1.3-only'):
        if not manifest_dict.get('attribution_notices'):
            return {"status": "REJECT", "reasons": ["Incomplete attribution: notices required"]}

    if manifest_dict.get('kind') in ('vector_art', 'visual_asset', 'artwork'):
        if not manifest_dict.get('artwork_provenance'):
            return {"status": "REJECT", "reasons": ["Missing artwork provenance"]}

    if manifest_dict.get('kind') in ('lexical', 'dictionary', 'morphology'):
         if not manifest_dict.get('lexical_provenance'):
            return {"status": "REJECT", "reasons": ["Missing lexical provenance"]}

    if manifest_dict.get('source_verification') == 'unverified_third_party':
        return {"status": "REJECT", "reasons": ["Copied from unverified third party"]}

    if status == "ACCEPT":
        receipt = {
            "receipt_id": hashlib.sha256((actual_hash + source).encode()).hexdigest(),
            "asset_hash": actual_hash,
            "license": license_id,
            "version": manifest_dict.get('version', '1.0')
        }

    result = {"status": status, "reasons": reasons}
    if receipt:
        result["receipt"] = receipt

    return result

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print("Usage: gate.py <manifest.json> [--repo-root ROOT]", file=sys.stderr)
        return 2

    manifest_path = Path(argv[0])
    repo_root = Path.cwd()
    if len(argv) >= 3 and argv[1] == '--repo-root':
        repo_root = Path(argv[2])

    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest: {e}", file=sys.stderr)
        return 2

    result = validate_contribution(manifest, repo_root)
    print(json.dumps(result, indent=2))

    if result["status"] == "REJECT":
        return 1
    elif result["status"] == "REVIEW_REQUIRED":
        return 3
    return 0

if __name__ == '__main__':
    sys.exit(main())
