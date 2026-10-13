"""Final Release Evidence Compiler"""

import argparse
import hashlib
import json
import os
import sys
import gzip
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def get_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def extract_pack_metadata(pack_path: Path) -> Dict[str, Any]:
    # Extracts lexical counts, cefr evidence, pack versions, source licenses, media identities from the pack
    # Since these are v1 legacy packs for now as seen in `zcat ar_universal_v1.pack.gz`, we extract what we can
    meta = {}
    try:
        with gzip.open(pack_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
            header = data.get("header", {})
            meta["pack_version"] = header.get("version", "unknown")
            meta["source_licenses"] = [header.get("license")] if header.get("license") else []
            meta["cefr_evidence"] = header.get("levels", [])
            # For lexical counts, it could be domains or words etc.
            meta["lexical_counts"] = {"domains": len(data.get("domains", []))}
            meta["media_identities"] = [d.get("icon_vector") for d in data.get("domains", []) if "icon_vector" in d]
    except Exception:
        pass
    return meta

def run_compiler(
    registry_path: Path,
    manifest_path: Path,
    packs_dir: Path,
    output_path: Path,
) -> Dict[str, Any]:
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    languages = registry.get("languages", [])
    if not isinstance(languages, list):
        raise ValueError("Invalid registry: languages must be a list")

    manifest_langs = {lang["code"]: lang for lang in manifest.get("languages", []) if isinstance(lang, dict) and "code" in lang}

    results = {}
    for lang in languages:
        code = lang["id"]
        manifest_lang = manifest_langs.get(code)

        if not manifest_lang:
            results[code] = {
                "status": "metadataOnly",
                "reason": "Missing from manifest.json"
            }
            continue

        pack_file = manifest_lang.get("pack_file")
        if not pack_file:
            results[code] = {
                "status": "metadataOnly",
                "reason": "No pack_file in manifest"
            }
            continue

        pack_path = packs_dir / pack_file
        if not pack_path.is_file():
            results[code] = {
                "status": "sourceMissing",
                "reason": f"Pack file {pack_file} not found"
            }
            continue

        expected_sha = manifest_lang.get("sha256")
        expected_size = manifest_lang.get("size_bytes")

        actual_size = pack_path.stat().st_size
        actual_sha = get_sha256(pack_path)

        if expected_size != actual_size or expected_sha != actual_sha:
            results[code] = {
                "status": "invalidPack",
                "reason": f"Hash or size mismatch for {pack_file}",
                "actual_size": actual_size,
                "actual_sha": actual_sha,
                "expected_size": expected_size,
                "expected_sha": expected_sha
            }
            continue

        # Check legacy asset status for license blocked
        legacy_status = manifest_lang.get("legacy_asset_status")
        if legacy_status in ["UNVERIFIED_LEGACY", "UNVERIFIED_RIGHTS"]:
            results[code] = {
                "status": "licenseBlocked",
                "reason": "Legacy asset status is unverified"
            }
            continue

        # Extract metadata from the pack
        pack_meta = extract_pack_metadata(pack_path)

        # Determine if verified or releaseReady
        # As per instructions: Only actually verified content is marked releaseReady.
        if manifest_lang.get("pack_verified") and manifest_lang.get("production_ready"):
            status = "releaseReady"
        else:
            status = "verified"

        results[code] = {
            "status": status,
            "pack_file": pack_file,
            "sha256": actual_sha,
            "size_bytes": actual_size,
            "domains_count": manifest_lang.get("domains_count", 0),
            "format": manifest_lang.get("format", "unknown"),
            "lexical_counts": pack_meta.get("lexical_counts", {}),
            "cefr_evidence": pack_meta.get("cefr_evidence", []),
            "pack_version": pack_meta.get("pack_version", manifest_lang.get("schemaVersion", "unknown")),
            "source_licenses": pack_meta.get("source_licenses", []),
            "media_identities": pack_meta.get("media_identities", [])
        }

    evidence_bundle = {
        "schema_version": "1.0.0",
        "evidence": results
    }

    # Atomic write to not overwrite previous valid bundle with failure
    temp_path = output_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(evidence_bundle, f, indent=2, sort_keys=True)
    temp_path.replace(output_path)

    return evidence_bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "catalog/language_registry.v1.json")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "manifest.json")
    parser.add_argument("--packs-dir", type=Path, default=REPO_ROOT / "packs")
    parser.add_argument("--output", type=Path, default=HERE / "evidence.json")
    args = parser.parse_args()

    try:
        run_compiler(args.registry, args.manifest, args.packs_dir, args.output)
        print("OK: Compiled evidence")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
