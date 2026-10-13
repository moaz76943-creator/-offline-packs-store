import argparse
import hashlib
import json
import os
import shutil
import zipfile
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

class ExportState(Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"

class ExportError(Exception):
    pass

def compute_sha256(filepath: str, chunk_size: int = 8192) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()

def secure_filename(filename: str) -> str:
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        raise ValueError(f"Invalid path: {filename}")
    return os.path.basename(filename)

class CommunityExporter:
    def __init__(self, source_dir: str, output_dir: str, previous_export_dir: Optional[str] = None):
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.previous_export_dir = previous_export_dir
        self.state = ExportState.READY
        self.events: List[Dict[str, Any]] = []
        self.version = "1.0.0"

    def validate_rights(self, artifact_meta: dict) -> bool:
        license_id = artifact_meta.get("license")
        approved_licenses = ["CC0-1.0", "CC-BY-4.0", "PUBLIC-DOMAIN", "OFL-1.1"]
        if not license_id or license_id not in approved_licenses:
            return False
        return True

    def validate_language_pair(self, lang_pair: str) -> bool:
        parts = lang_pair.split("-")
        if len(parts) not in [1, 2]:
            return False
        for p in parts:
            if not (2 <= len(p) <= 3 and p.isalpha() and p.islower()):
                return False
        return True

    def validate_vector(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, 'rb') as f:
                header = f.read(4)
                if not header:
                    return False
            return True
        except Exception:
            return False

    def build_deterministic_zip(self, archive_path: str, files: List[Tuple[str, str]], attribution_text: str) -> str:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            sorted_files = sorted(files, key=lambda x: x[1])
            for filepath, arcname in sorted_files:
                zinfo = zipfile.ZipInfo(arcname, date_time=(2024, 1, 1, 0, 0, 0))
                zinfo.external_attr = 0o644 << 16
                # Bounded memory chunking during packaging
                with open(filepath, 'rb') as f:
                    with zf.open(zinfo, 'w') as zf_out:
                        shutil.copyfileobj(f, zf_out)

            # Add attribution
            attr_info = zipfile.ZipInfo("ATTRIBUTION.txt", date_time=(2024, 1, 1, 0, 0, 0))
            attr_info.external_attr = 0o644 << 16
            zf.writestr(attr_info, attribution_text.encode('utf-8'))

        return compute_sha256(archive_path)

    def run(self) -> ExportState:
        # Avoid putting staging directly inside output dir if we plan to atomic rename the whole dir,
        # but the request is for atomic staging "before final publication" and moving files one by one
        # is what we had. We can make it atomic using temp dir rename.
        import tempfile
        import uuid

        tmp_staging_dir = os.path.join(tempfile.gettempdir(), f"export_staging_{uuid.uuid4().hex}")
        os.makedirs(tmp_staging_dir, exist_ok=True)

        try:
            manifest_path = os.path.join(self.source_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                self.state = ExportState.FAILED
                self.events.append({"event": "error", "message": "Missing manifest.json"})
                return self.state

            with open(manifest_path, 'r') as f:
                manifest = json.load(f)

            current_manifest = {"version": self.version, "artifacts": {}}

            for item in manifest.get("items", []):
                artifact_id = item["id"]

                # Circuit-breaker / Missing validation evidence
                if "evidence" not in item:
                    self.state = ExportState.BLOCKED
                    self.events.append({"event": "blocked_no_evidence", "artifact": artifact_id})
                    continue

                if not self.validate_rights(item):
                    self.state = ExportState.BLOCKED
                    self.events.append({"event": "blocked_rights", "artifact": artifact_id})
                    continue

                lang_pair = item.get("lang_pair")
                if lang_pair and not self.validate_language_pair(lang_pair):
                    self.state = ExportState.FAILED
                    self.events.append({"event": "invalid_lang_pair", "artifact": artifact_id})
                    continue

                if item.get("type") == "learner_progress":
                    # Exclude private learner progress
                    continue

                try:
                    filename = secure_filename(item["filename"])
                except ValueError:
                    self.state = ExportState.FAILED
                    self.events.append({"event": "unsafe_path", "artifact": artifact_id})
                    continue

                src_file = os.path.join(self.source_dir, filename)
                if not os.path.exists(src_file):
                    self.state = ExportState.FAILED
                    self.events.append({"event": "missing_file", "artifact": artifact_id})
                    continue

                actual_hash = compute_sha256(src_file)
                if actual_hash != item.get("sha256"):
                    self.state = ExportState.FAILED
                    self.events.append({"event": "stale_hash", "artifact": artifact_id})
                    continue

                if item.get("type") == "vector":
                    if not self.validate_vector(src_file):
                        self.state = ExportState.FAILED
                        self.events.append({"event": "damaged_vector", "artifact": artifact_id})
                        continue

                # Attribution text
                provenance = item.get("provenance", "Community Contribution")
                license_id = item.get("license")
                attr_text = f"Artifact: {artifact_id}\nProvenance: {provenance}\nLicense: {license_id}\n"

                out_filename = f"{artifact_id}.zip"
                out_path = os.path.join(tmp_staging_dir, out_filename)

                # Incremental Check before building
                unchanged = False
                zip_hash = ""
                size = 0

                if self.previous_export_dir:
                    prev_manifest_path = os.path.join(self.previous_export_dir, "manifest.json")
                    if os.path.exists(prev_manifest_path):
                        with open(prev_manifest_path, 'r') as f:
                            prev_manifest = json.load(f)
                        prev_art = prev_manifest.get("artifacts", {}).get(artifact_id)

                        # We use actual_hash (source file hash) to determine if it changed,
                        # and verify the previous archive exists and is valid.
                        if prev_art and prev_art.get("src_sha256") == actual_hash:
                            prev_path = os.path.join(self.previous_export_dir, out_filename)
                            if os.path.exists(prev_path):
                                prev_zip_hash = compute_sha256(prev_path)
                                if prev_zip_hash == prev_art.get("sha256"):
                                    unchanged = True
                                    zip_hash = prev_zip_hash
                                    size = prev_art.get("size")
                                    shutil.copy2(prev_path, out_path)

                if unchanged:
                    self.events.append({"event": "unchanged", "artifact": artifact_id})
                else:
                    zip_hash = self.build_deterministic_zip(out_path, [(src_file, filename)], attr_text)
                    size = os.path.getsize(out_path)

                    self.events.append({
                        "event": "update",
                        "artifact": artifact_id,
                        "hash": zip_hash,
                        "size": size
                    })

                current_manifest["artifacts"][artifact_id] = {
                    "filename": out_filename,
                    "sha256": zip_hash,
                    "src_sha256": actual_hash,
                    "size": size,
                    "type": item.get("type"),
                    "license": license_id,
                    "provenance": provenance
                }

            if self.state in [ExportState.FAILED, ExportState.BLOCKED, ExportState.REVIEW_REQUIRED]:
                shutil.rmtree(tmp_staging_dir)
                return self.state

            with open(os.path.join(tmp_staging_dir, "manifest.json"), 'w') as f:
                json.dump(current_manifest, f, indent=2, sort_keys=True)

            # Atomic move by renaming directory into final location, or copy/replace safely
            # Note: os.rename is atomic if on the same filesystem. We can move the whole output_dir
            # if we first empty it out, or move the temp dir as the new output_dir.
            # But the requirement says "stage all output atomically before final publication".
            import uuid

            # To be truly atomic, we can rename tmp_staging_dir to a final atomic folder,
            # or rename the existing output_dir out of the way, and rename staging to output_dir.
            # Here we move tmp_staging to output_dir directly. If output_dir exists, we can
            # use a temporary swap.
            swap_dir = os.path.join(os.path.dirname(self.output_dir), f".old_output_{uuid.uuid4().hex}")
            try:
                # Atomically swap by moving the entire tmp_staging_dir to self.output_dir.
                # If self.output_dir exists, we might need to remove/swap it.
                if os.path.exists(self.output_dir):
                    os.rename(self.output_dir, swap_dir)

                os.rename(tmp_staging_dir, self.output_dir)

                if os.path.exists(swap_dir):
                    shutil.rmtree(swap_dir)
            except Exception as e:
                # Rollback
                if os.path.exists(swap_dir) and not os.path.exists(self.output_dir):
                    os.rename(swap_dir, self.output_dir)
                raise e

            self.state = ExportState.READY
            return self.state

        except Exception as e:
            shutil.rmtree(tmp_staging_dir, ignore_errors=True)
            self.state = ExportState.FAILED
            self.events.append({"event": "error", "message": str(e)})
            return self.state

def main():
    parser = argparse.ArgumentParser(description="Continuous Community Open-Content Exporter")
    parser.add_argument("--source", required=True, help="Source directory containing community datasets")
    parser.add_argument("--output", required=True, help="Output directory for exported packages")
    parser.add_argument("--previous", help="Previous export directory for incremental checks")
    args = parser.parse_args()

    exporter = CommunityExporter(args.source, args.output, args.previous)
    state = exporter.run()

    print(f"Export State: {state.value}")
    print("Events:")
    for event in exporter.events:
        print(json.dumps(event))

if __name__ == "__main__":
    main()
