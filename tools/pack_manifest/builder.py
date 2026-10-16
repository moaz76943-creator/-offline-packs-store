import gzip
import json
import zlib
import hashlib
import os

class ManifestBuilder:
    def __init__(self):
        self.MAX_SIZE = 50 * 1024 * 1024 # 50 MB bound
        self.SCHEMA_VERSION = "1.0"

    def _safe_read(self, filepath):
        if not os.path.exists(filepath):
            raise ValueError(f"File does not exist: {filepath}")

        # Reject untrusted external paths and directory traversal
        norm_path = os.path.normpath(filepath)
        if '..' in norm_path.split(os.sep):
            raise ValueError(f"Untrusted path rejected: {filepath}")

        stat = os.stat(filepath)
        if stat.st_size > self.MAX_SIZE:
            raise ValueError("File exceeds maximum bounded size")

        with open(filepath, 'rb') as f:
            return f.read()

    def build_manifest(self, filepath):
        compressed = self._safe_read(filepath)

        is_gz = filepath.endswith('.pack.gz')
        is_vct = filepath.endswith('.vct')

        if not (is_gz or is_vct):
            raise ValueError("Unsupported extension. Only .pack.gz and .vct are supported")

        try:
            if is_gz:
                raw_data = gzip.decompress(compressed)
            else:
                raw_data = zlib.decompress(compressed)

            data = json.loads(raw_data.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Invalid format or parsing error: {e}")

        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "pack_id": os.path.basename(filepath),
            "byte_size": len(compressed),
            "sha256": hashlib.sha256(compressed).hexdigest(),
        }

        if is_gz:
            if "header" in data: # Universal v1
                manifest["language"] = data["header"].get("code")
                manifest["license"] = data["header"].get("license")
                actual_count = len(data.get("domains", []))
                expected_count = data["header"].get("terms_count", actual_count)
            else: # Core A1
                manifest["language"] = data.get("lang_code", data.get("language"))
                manifest["license"] = data.get("license")
                if "terms" in data:
                    actual_count = len(data["terms"])
                elif "vocabulary" in data:
                    actual_count = len(data["vocabulary"])
                else:
                    actual_count = data.get("terms_count", 0)
                expected_count = data.get("terms_count", actual_count)

        else: # Semantic-vector asset pack
            manifest["language"] = data.get("language")
            manifest["license"] = data.get("license")
            if "paths" in data:
                actual_count = len(data.get("paths", []))
            else:
                actual_count = 1
            expected_count = actual_count

        if actual_count != expected_count:
            raise ValueError(f"Mismatched entry count for {filepath}. Expected {expected_count}, actual {actual_count}")

        manifest["entry_count"] = actual_count
        manifest["dependencies"] = data.get("dependencies", [])
        manifest["provenance"] = data.get("provenance", "unknown")

        return manifest


def build_system_manifest(directory, previous_manifest_path=None):
    """ Builds a manifest for all packs in a directory """
    builder = ManifestBuilder()
    packs = []

    for root, dirs, files in os.walk(directory):
        dirs.sort() # Ensure deterministic directory iteration
        for f in sorted(files):
            if f.endswith('.pack.gz') or f.endswith('.vct'):
                path = os.path.join(root, f)
                try:
                    pack_man = builder.build_manifest(path)
                    packs.append(pack_man)
                except Exception as e:
                    raise ValueError(f"Failed to build manifest for {path}: {e}")

    new_manifest = {
        "schema_version": builder.SCHEMA_VERSION,
        "packs": packs
    }

    if previous_manifest_path and os.path.exists(previous_manifest_path):
        try:
            with open(previous_manifest_path, 'r') as f:
                old_manifest = json.load(f)
            plan = generate_update_plan(old_manifest, new_manifest)
        except Exception:
            # Preserve previous behavior if corrupt, treat as if old doesn't exist
            plan = generate_update_plan({"packs": []}, new_manifest)
    else:
        plan = generate_update_plan({"packs": []}, new_manifest)

    return new_manifest, plan


def generate_update_plan(old_manifest, new_manifest):
    plan = {
        "unchanged": [],
        "updated": [],
        "added": [],
        "removed": []
    }

    old_packs = {p["pack_id"]: p for p in old_manifest.get("packs", [])}
    new_packs = {p["pack_id"]: p for p in new_manifest.get("packs", [])}

    for pack_id, new_data in new_packs.items():
        if pack_id not in old_packs:
            plan["added"].append(pack_id)
        else:
            old_data = old_packs[pack_id]
            # Check if payload delta
            if old_data.get("sha256") == new_data.get("sha256"):
                plan["unchanged"].append(pack_id)
            else:
                plan["updated"].append(pack_id)

    for pack_id in old_packs:
        if pack_id not in new_packs:
            plan["removed"].append(pack_id)

    # Track broken dependencies if referenced but not found
    all_known_packs = set(new_packs.keys())
    for pack_id, pack_data in new_packs.items():
        deps = pack_data.get("dependencies", [])
        for dep in deps:
            if dep not in all_known_packs:
                if "broken_dependencies" not in plan:
                    plan["broken_dependencies"] = {}
                if pack_id not in plan["broken_dependencies"]:
                    plan["broken_dependencies"][pack_id] = []
                plan["broken_dependencies"][pack_id].append(dep)

    return plan
