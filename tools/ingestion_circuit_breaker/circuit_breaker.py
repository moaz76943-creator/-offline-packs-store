import argparse
import sys
import os
import json
from pathlib import Path

import hashlib
import time

def generate_hash(filepath: Path) -> str:
    """Generates SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def issue_admission(source_filepath: Path, license_version: str, destination: Path) -> dict:
    """
    Issues a short-lived, content-bound admission manifest.
    Binds admission to source hash, license version, and destination.
    """
    source_hash = generate_hash(source_filepath)
    # Short-lived token, valid for 5 minutes (300 seconds)
    expiry = int(time.time()) + 300

    admission_manifest = {
        "source_hash": source_hash,
        "license_version": license_version,
        "destination": str(destination),
        "expiry": expiry,
        "status": "VALID"
    }
    return admission_manifest

import shutil

def quarantine_source(source_filepath: Path, quarantine_dir: Path):
    """
    Quarantines invalid input into a separate controlled staging area
    without destroying original evidence.
    """
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    destination = quarantine_dir / source_filepath.name
    # Using copy2 to preserve metadata (original evidence)
    shutil.copy2(source_filepath, destination)
    print(f"Quarantined {source_filepath.name} to {quarantine_dir}", file=sys.stderr)

def evaluate_license_compatibility(license_status: str, manifest_path: Path) -> bool:
    """
    Evaluates whether the provided license_status is compatible with the
    intended distribution output as defined in the manifest.json
    """
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
            expected_status = manifest_data.get('intellectual_property_status', '')
            # Normalizing to uppercase and removing spaces/underscores for robust checking
            norm_expected = expected_status.upper().replace(' ', '').replace('_', '')
            norm_actual = license_status.upper().replace(' ', '').replace('_', '')
            if norm_actual == norm_expected or license_status == 'PUBLIC_DOMAIN_ZERO_COPYRIGHT':
                 return True
            return False
    except Exception as e:
        print(f"Error reading manifest: {e}", file=sys.stderr)
        return False

def process_ingestion(args, repo_root: Path):
    """
    Main logic for processing the ingestion, tying validation, evaluation,
    quarantine, and admission issuance.
    """
    if not args.source.exists():
        print(f"ERROR: Source file {args.source} not found.", file=sys.stderr)
        sys.exit(1)

    if not args.provenance.exists():
        print(f"ERROR: Provenance file {args.provenance} not found.", file=sys.stderr)
        quarantine_source(args.source, args.quarantine)
        sys.exit(1)

    try:
        with open(args.provenance, 'r', encoding='utf-8') as f:
            provenance_data = json.load(f)
    except Exception as e:
        print(f"ERROR: Invalid provenance file format: {e}", file=sys.stderr)
        quarantine_source(args.source, args.quarantine)
        sys.exit(1)

    license_status = provenance_data.get('license', '')
    if not license_status:
        print("ERROR: Missing license data in provenance.", file=sys.stderr)
        quarantine_source(args.source, args.quarantine)
        sys.exit(1)

    manifest_path = repo_root / 'manifest.json'
    if not evaluate_license_compatibility(license_status, manifest_path):
        print(f"ERROR: License '{license_status}' is incompatible with manifest.", file=sys.stderr)
        quarantine_source(args.source, args.quarantine)
        sys.exit(1)

    expected_hash = provenance_data.get('source_hash', '')
    actual_hash = generate_hash(args.source)
    if expected_hash and actual_hash != expected_hash:
        print(f"ERROR: Altered source bytes. Expected {expected_hash}, got {actual_hash}.", file=sys.stderr)
        quarantine_source(args.source, args.quarantine)
        sys.exit(1)

    admission = issue_admission(args.source, license_status, args.destination)

    # 13. If actual ingestion integration requires unavailable interfaces
    if args.integrate:
        print("BLOCKED_INTEGRATION: Actual integration with production interfaces is not available.", file=sys.stderr)
        # Exit with 0 because the *gate* successfully blocked integration without falsely claiming enforcement
        sys.exit(0)

    # Print admission manifest to stdout
    print(json.dumps(admission, indent=2))
    return admission


def main():
    parser = argparse.ArgumentParser(description="Automated Ingestion Circuit Breaker")
    parser.add_argument("--source", type=Path, required=True, help="Path to the source file")
    parser.add_argument("--provenance", type=Path, required=True, help="Path to the provenance/license ledger")
    parser.add_argument("--destination", type=Path, required=True, help="Intended output destination")
    parser.add_argument("--quarantine", type=Path, required=True, help="Quarantine directory for invalid sources")
    parser.add_argument("--integrate", action="store_true", help="Attempt integration with production interfaces")

    args = parser.parse_args()

    # 1. Verify repository access before execution
    repo_root = Path.cwd()
    if not (repo_root / 'manifest.json').exists():
        print("ERROR: Must be run from repository root", file=sys.stderr)
        sys.exit(1)

    process_ingestion(args, repo_root)

if __name__ == "__main__":
    main()
