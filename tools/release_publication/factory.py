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

def verify_publication_eligibility(repo_root, artifacts_json_path, output_path):
    """Ensure artifacts are ready for publication by calling release gate."""
    # Reuse release gate tools/release_validation/validator.py
    gate_script = repo_root / "tools/release_validation/validator.py"
    if not gate_script.is_file():
        raise ValueError("Release validation script missing")

    result = subprocess.run(
        [sys.executable, str(gate_script), "--repo-root", str(repo_root), "--candidates", str(artifacts_json_path), "--output", str(output_path)],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise ValueError(f"Release gate blocked publication: {result.stdout.strip()}")

    try:
        evidence = json.loads(result.stdout)
    except Exception:
        raise ValueError("Release gate output is not valid json")

    for art_id, statuses in evidence.items():
        if statuses != ["PASSED"]:
            raise ValueError(f"Not a verified candidate: {art_id} -> {statuses}")

    return evidence

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
    env["PYTHONPATH"] = str(repo_root)

    # Decompress `.pack.gz` archives to a temporary `.db` database before validating
    tmp_fd, tmp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)

    try:
        with gzip.open(path, 'rb') as f_in:
            with open(tmp_db_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        result = subprocess.run(
            [sys.executable, str(check_script), tmp_db_path, "--structural-only"],
            capture_output=True,
            text=True,
            env=env
        )
        if result.returncode != 0:
            raise ValueError(f"Pack conformance check failed: {result.stdout.strip()} {result.stderr.strip()}")
    finally:
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)

def generate_provenance(repo_root, manifest_out, notice_out):
    compiler_script = repo_root / "tools/provenance_release/compiler.py"
    if not compiler_script.is_file():
        raise ValueError("Provenance compiler missing")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [sys.executable, str(compiler_script), "--repo-root", str(repo_root), "--manifest-out", str(manifest_out), "--notice-out", str(notice_out)],
        capture_output=True,
        text=True,
        env=env
    )
    if result.returncode != 0:
        raise ValueError(f"Provenance generation failed: {result.stdout.strip()} {result.stderr.strip()}")


def publish_artifacts(repo_root, target_dir, artifacts_json_path, dry_run=False, check_auth=True):
    repo_root = Path(repo_root).resolve()
    target = Path(target_dir).resolve()
    artifacts_json_path = Path(artifacts_json_path).resolve()

    try:
        target.relative_to(repo_root)
    except ValueError:
        if not dry_run:
            raise ValueError("Target directory must be within repository") from None

    with open(artifacts_json_path, 'r') as f:
        artifacts_data = json.load(f)
        artifacts = artifacts_data.get('artifacts', [])

    if check_auth:
        verify_publication_authorization(repo_root)

        # Use a temporary file for the verified output of the validation gate
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_out:
            tmp_out_path = tmp_out.name
        try:
            verify_publication_eligibility(repo_root, artifacts_json_path, tmp_out_path)
        finally:
            if os.path.exists(tmp_out_path):
                os.remove(tmp_out_path)

    # verify all gates and files
    for entry in artifacts:
        path_str = entry.get('path')
        if not path_str:
            raise ValueError("Missing path in artifact entry")

        path = (repo_root / path_str).resolve()
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

            # Generate release_provenance.json and NOTICE.txt
            generate_provenance(repo_root, tmp_path / "release_provenance.json", tmp_path / "NOTICE.txt")

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
        publish_artifacts(args.repo_root, args.target_dir, args.artifacts_json, args.dry_run, not args.skip_auth)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
