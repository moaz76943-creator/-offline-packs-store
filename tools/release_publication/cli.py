import argparse
import sys
import json
import hashlib
import tarfile
import tempfile
import shutil
import os
from pathlib import Path

def compute_sha256(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()

def run_pipeline(manifest_path, packs_dir, output_path, dry_run=False, publish=False, credentials=None):
    if publish and not credentials:
        raise ValueError("Credentials required for publication")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if manifest.get("intellectual_property_status") != "PUBLIC_DOMAIN_ZERO_COPYRIGHT":
        raise ValueError("Intellectual property status must be PUBLIC_DOMAIN_ZERO_COPYRIGHT")

    languages = manifest.get("languages", [])
    valid_formats = {"legacy-json-gzip", "json-gzip-v1"}

    for lang in languages:
        pack_file = lang.get("pack_file")
        if not pack_file:
            raise ValueError(f"Language {lang.get('code')} is missing pack_file")

        pack_path = packs_dir / pack_file
        if not pack_path.exists():
            raise ValueError(f"Pack file {pack_file} does not exist")

        expected_sha256 = lang.get("sha256")
        if not expected_sha256:
            raise ValueError(f"Language {lang.get('code')} is missing sha256")

        actual_sha256 = compute_sha256(pack_path)
        if actual_sha256 != expected_sha256:
            raise ValueError(f"SHA256 mismatch for {pack_file}. Expected {expected_sha256}, got {actual_sha256}")

        fmt = lang.get("format")
        if fmt not in valid_formats:
            raise ValueError(f"Unsupported format {fmt} for language {lang.get('code')}")

    if dry_run:
        return

    # Add attribution
    manifest_copy = manifest.copy()
    manifest_copy["attribution"] = "Open-content catalog semantic asset package. Verified public release."

    try:
        temp_path = str(output_path) + ".tmp"
        # Ensure identical ordering of manifest keys when dumping
        def get_deterministic_json_bytes(obj):
            return json.dumps(obj, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode('utf-8')

        manifest_json = get_deterministic_json_bytes(manifest_copy)

        import gzip
        with open(temp_path, "wb") as f:
            with gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
                    # Add manifest
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(manifest_json)
                    info.mtime = 0  # deterministic
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    tar.addfile(info, __import__("io").BytesIO(manifest_json))

                    # Add packs
                    for lang in sorted(languages, key=lambda x: x.get("pack_file", "")):
                        pack_file = lang.get("pack_file")
                        pack_path = packs_dir / pack_file
                        info = tarfile.TarInfo(f"packs/{pack_file}")
                        info.size = pack_path.stat().st_size
                        info.mtime = 0  # deterministic
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        with open(pack_path, "rb") as pack_f:
                            tar.addfile(info, pack_f)

        # Atomic rename
        shutil.move(temp_path, output_path)

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e


def main():
    parser = argparse.ArgumentParser(description="Verified Public Release Publication Factory")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to manifest.json")
    parser.add_argument("--packs-dir", type=Path, required=True, help="Directory containing .pack.gz files")
    parser.add_argument("--output", type=Path, required=True, help="Output path for the publication archive (.tar.gz)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without generating output archive")
    parser.add_argument("--publish", action="store_true", help="Authorize explicit publication")
    parser.add_argument("--credentials", type=str, help="Publication credentials (required if --publish is set)")

    args = parser.parse_args()

    try:
        run_pipeline(args.manifest, args.packs_dir, args.output, args.dry_run, args.publish, args.credentials)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
