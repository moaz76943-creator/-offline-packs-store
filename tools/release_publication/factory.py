#!/usr/bin/env python3
"""Verified Public Release Publication Factory"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import gzip
from pathlib import Path

MAX_FILE_SIZE = 100 * 1024 * 1024

def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def verify_publication_eligibility(repo_root, artifacts):
    """Ensure artifacts are ready for publication by calling release eligibility gate."""
    validator_script = repo_root / "tools/release_validation/validator.py"
    if not validator_script.is_file():
        raise ValueError("Release eligibility validator missing")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        candidates_json = tmp_path / "candidates.json"
        candidates_json.write_text(json.dumps({"artifacts": artifacts}))
        output_json = tmp_path / "approved.json"

        result = subprocess.run(
            [sys.executable, str(validator_script), "--repo-root", str(repo_root),
             "--candidates", str(candidates_json), "--output", str(output_json)],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise ValueError(f"Release gate blocked publication: {result.stdout.strip()}")

        try:
            approved = json.loads(output_json.read_text())
            if not isinstance(approved.get('approved_artifacts'), list) or len(approved['approved_artifacts']) != len(artifacts):
                raise ValueError("Not all artifacts were approved")
        except Exception as e:
            raise ValueError(f"Failed to read approved artifacts: {e}")

def verify_publication_authorization(repo_root):
    """Prevent remote publication without valid credentials and previously approved policy."""
    creds_path = repo_root / ".credentials/publisher"
    if not creds_path.is_file():
        raise ValueError("Unauthorized: Missing credentials")

def verify_pack_conformance(repo_root, path, sha, language):
    check_script = repo_root / "tools/pack_conformance/validator.py"
    if not check_script.is_file():
        raise ValueError("Conformance check missing")

    env = os.environ.copy()
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(repo_root)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "content.db"

        # Decompress .pack.gz to .db
        try:
            with gzip.open(path, 'rb') as f_in:
                with open(db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except Exception as e:
            raise ValueError(f"Failed to decompress {path}: {e}")

        result = subprocess.run(
            [sys.executable, str(check_script), str(db_path), "--structural-only"],
            capture_output=True,
            text=True,
            env=env
        )
        if result.returncode != 0:
            raise ValueError(f"Pack conformance check failed: {result.stderr.strip()}")

def write_attribution(repo_root, artifacts, target_dir):
    compiler_script = repo_root / "tools/provenance_release/compiler.py"
    if not compiler_script.is_file():
        raise ValueError("Provenance compiler missing")

    env = os.environ.copy()
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(repo_root)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()

        # convert artifacts format to daily release candidates format
        candidates = []
        for entry in artifacts:
             candidates.append({
                  "asset_id": entry.get("id", entry.get("path")),
                  "kind": "lexical_pack" if entry["path"].endswith(".pack.gz") else "vector_art",
                  "artifact_path": entry["path"],
                  "sha256": entry["sha256"],
                  "output_license_id": entry.get("license", "CC-BY-SA-4.0"),
                  "source_refs": entry.get("source_refs", [])
             })

        daily_file = daily_dir / "daily.json"
        daily_file.write_text(json.dumps({
             "schema_version": "1.0.0",
             "release_candidates": candidates
        }))

        manifest_out = target_dir / "release_provenance.json"
        notice_out = target_dir / "NOTICE.txt"

        result = subprocess.run(
            [sys.executable, str(compiler_script), "--repo-root", str(repo_root),
             "--daily-dir", str(daily_dir), "--manifest-out", str(manifest_out), "--notice-out", str(notice_out)],
            capture_output=True,
            text=True,
            env=env
        )
        if result.returncode != 0:
            raise ValueError(f"Provenance compilation failed: {result.stderr.strip()}")

def publish_artifacts(repo_root, target_dir, artifacts, dry_run=False, check_auth=True):
    repo_root = Path(repo_root).resolve()
    target = Path(target_dir).resolve()

    try:
        target.relative_to(repo_root)
    except ValueError:
        if not dry_run:
            raise ValueError("Target directory must be within repository") from None

    if check_auth:
        verify_publication_eligibility(repo_root, artifacts)
        verify_publication_authorization(repo_root)

    # verify all gates and files
    for entry in artifacts:
        path = (repo_root / entry['path']).resolve()
        try:
             path.relative_to(repo_root)
        except ValueError:
             raise ValueError("Path traversal detected")

        if not path.is_file():
            raise ValueError(f"Artifact {entry['path']} does not exist")
        if path.is_symlink():
            raise ValueError("Artifacts cannot be symlinks")
        if path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError("Artifact exceeds size limit")
        actual_hash = file_hash(path)
        if actual_hash != entry['sha256']:
            raise ValueError(f"Hash mismatch for {entry['path']}")

        if not (entry['path'].endswith('.pack.gz') or entry['path'].endswith('.vct')):
             raise ValueError("Unsupported format")

        if check_auth and entry['path'].endswith('.pack.gz'):
             lang = entry.get('language')
             if not lang:
                 raise ValueError("Language required for pack conformance check")
             verify_pack_conformance(repo_root, path, entry['sha256'], lang)

    if not dry_run:
        # Atomic staging using a temporary directory, replacing target on success
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = tempfile.mkdtemp(dir=target.parent)
        tmp_path = Path(tmp_dir)
        try:
            for entry in artifacts:
                src = (repo_root / entry['path']).resolve()
                dst = tmp_path / src.name
                shutil.copy2(src, dst)

                # Write individual manifest preserving versions and schema
                manifest = tmp_path / f"{src.name}.manifest.json"
                manifest.write_text(json.dumps({
                    "source": str(entry['path']),
                    "sha256": entry['sha256'],
                    "language": entry.get('language', 'unknown'),
                    "version": entry.get('version', '0.0.0'),
                    "schema": entry.get('schema', 'v2'),
                    "provenance": entry.get('provenance', []),
                    "attribution": entry.get('attribution', 'No attribution provided'),
                    "published": True
                }, indent=2) + "\n")

            # Write global attribution if applicable
            write_attribution(repo_root, artifacts, tmp_path)

            # preserve last verified if exists
            if target.exists():
                backup = target.with_name(target.name + '.bak')
                if backup.exists():
                    shutil.rmtree(backup)
                target.rename(backup)

            tmp_path.rename(target)

            # Cleanup backup if successful
            if target.with_name(target.name + '.bak').exists():
                shutil.rmtree(target.with_name(target.name + '.bak'))

        except Exception as e:
            shutil.rmtree(tmp_path, ignore_errors=True)
            # Restore backup if it exists
            backup = target.with_name(target.name + '.bak')
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise e

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--target-dir', type=Path, required=True)
    parser.add_argument('--artifacts-json', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--skip-auth', action='store_true', help="Skip authorization check for tests")
    args = parser.parse_args()

    try:
        artifacts = json.loads(args.artifacts_json.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error loading artifacts manifest: {e}", file=sys.stderr)
        return 1

    try:
        publish_artifacts(args.repo_root, args.target_dir, artifacts, args.dry_run, not args.skip_auth)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
