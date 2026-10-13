#!/usr/bin/env python3
"""Fail-closed offline ingestion circuit breaker."""
import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from legal.ledger.admission import LICENSES, OBLIGATIONS
except ImportError:
    print("BLOCKED_INTEGRATION: Required interfaces unavailable.", file=sys.stderr)
    sys.exit(3)

MAX_INPUT = 100 * 1024 * 1024  # 100MB bound


def check_repo_access(root):
    if not Path(root).is_dir() or not (Path(root) / ".git").exists():
         print("BLOCKED_INTEGRATION: Repository access verification failed.", file=sys.stderr)
         sys.exit(3)


def read_file_safe(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("symlink or missing file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_INPUT:
            raise ValueError("unsafe or oversized input")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(MAX_INPUT + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_INPUT:
        raise ValueError("input exceeds size limit")
    return data

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def evaluate(manifest, source_content, allowed_output_licenses):
    out = []

    if not isinstance(manifest, dict):
        return ["SCHEMA: manifest must be an object"]

    source_id = manifest.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        out.append("SCHEMA: missing source_id")

    license_id = manifest.get("license_id")
    if license_id not in LICENSES:
        out.append("BLOCKED_LICENSE: unknown or unsupported license")

    expected_hash = manifest.get("artifact_sha256")
    actual_hash = sha256_bytes(source_content)

    if not expected_hash or expected_hash != actual_hash:
        out.append("HASH_MISMATCH: artifact differs from recorded SHA-256")

    output_license = manifest.get("output_license_id")
    if output_license not in allowed_output_licenses:
         out.append("BLOCKED_LICENSE: intended output license is incompatible or forbidden")

    if license_id in OBLIGATIONS and output_license != license_id:
        out.append("LICENSE_CONFLICT: cannot relicense from copyleft")

    if license_id == "CC0-1.0" and output_license == "PUBLIC-DOMAIN":
        out.append("LICENSE_CONFLICT: CC0 is not a blanket public-domain claim")

    if license_id == "PUBLIC-DOMAIN" and output_license != "PUBLIC-DOMAIN":
         out.append("LICENSE_CONFLICT: cannot relicense from public domain to copyleft")

    return out

def is_expired(admission_data):
    try:
        issued = datetime.fromisoformat(admission_data["issued_at"])
        return datetime.now(timezone.utc) - issued > timedelta(hours=1)
    except (KeyError, ValueError, TypeError):
        return True

def issue_admission(manifest, content_hash):
    return {
        "admission_id": hashlib.sha256((manifest.get("source_id", "") + content_hash + str(time.time())).encode()).hexdigest(),
        "source_id": manifest.get("source_id"),
        "license_id": manifest.get("license_id"),
        "output_license_id": manifest.get("output_license_id"),
        "artifact_sha256": content_hash,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "status": "ADMITTED"
    }

def quarantine(source_content, staging_root, reason):
    root = Path(staging_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rejected = root / "quarantined"
    rejected.mkdir(exist_ok=True)

    digest = sha256_bytes(source_content)
    original = rejected / (digest + ".bin")
    receipt_path = rejected / (digest + ".json")

    receipt = {
        "sha256": digest,
        "state": "QUARANTINED",
        "reason": str(reason)[:200]
    }

    if not original.exists():
        with open(original, "wb") as f:
            f.write(source_content)

    if not receipt_path.exists():
        with open(receipt_path, "w") as f:
            json.dump(receipt, f, sort_keys=True)

    return receipt

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--allowed-outputs", nargs="+", default=list(LICENSES))
    parser.add_argument("--verify-token", type=Path, help="Verify an existing admission token")
    args = parser.parse_args(argv)

    check_repo_access(args.repo_root)

    if args.verify_token:
        try:
            token_data = json.loads(read_file_safe(args.verify_token))
            if is_expired(token_data):
                print("BLOCK TOKEN_EXPIRED: admission token has expired")
                return 1
            if token_data.get("status") != "ADMITTED":
                print("BLOCK TOKEN_REVOKED: admission token is not ADMITTED")
                return 1
            print("TOKEN VALID")
            return 0
        except Exception as e:
            print(f"BLOCK INVALID_TOKEN: {e}", file=sys.stderr)
            return 1

    try:
        source_content = read_file_safe(args.source)
        manifest_content = json.loads(read_file_safe(args.manifest))
    except Exception as e:
        print("EVIDENCE: cannot read admission inputs:", e, file=sys.stderr)
        return 2

    errors = evaluate(manifest_content, source_content, args.allowed_outputs)

    if errors:
        quarantine(source_content, args.staging_root, "; ".join(errors))
        for e in errors:
            print("BLOCK " + e)
        print(f"NO-GO: {len(errors)} distinct blockers")
        return 1

    admission = issue_admission(manifest_content, sha256_bytes(source_content))

    root = Path(args.staging_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    admitted = root / "admitted"
    admitted.mkdir(exist_ok=True)

    with open(admitted / (admission["admission_id"] + ".json"), "w") as f:
         json.dump(admission, f, sort_keys=True)

    print(json.dumps(admission))
    return 0

if __name__ == "__main__":
    sys.exit(main())
