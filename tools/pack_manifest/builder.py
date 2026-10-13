import json
import gzip
import hashlib
import os
import tempfile

class ManifestBuilderError(Exception):
    pass

class ManifestBuilder:
    def __init__(self, packs_dir="packs"):
        self.packs_dir = os.path.abspath(packs_dir)
        self.max_file_size = 50 * 1024 * 1024  # 50 MB limit
        self.max_manifest_size = 10 * 1024 * 1024 # 10 MB limit
        self.schema_version = "2.0.0"

    def _safe_path(self, filepath):
        abs_path = os.path.abspath(filepath)
        # Using os.path.commonpath for strict checking
        if os.path.commonpath([self.packs_dir, abs_path]) != self.packs_dir:
            raise ManifestBuilderError(f"Path traversal detected: {filepath}")
        return abs_path

    def sha256_file(self, filepath):
        if not os.path.exists(filepath):
            raise ManifestBuilderError(f"Missing artifact: {filepath}")
        h = hashlib.sha256()
        size = 0
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                size += len(chunk)
                if size > self.max_file_size:
                    raise ManifestBuilderError(f"File {filepath} exceeds size limit")
                h.update(chunk)
        return size, h.hexdigest()

    def _extract_pack_info(self, filepath):
        try:
            with gzip.open(filepath, 'rt', encoding='utf-8') as f:
                data = json.load(f)

                pack_info = {
                    "language": None,
                    "pack_id": os.path.basename(filepath),
                    "schema_version": data.get("version", data.get("schemaVersion", "1.0.0")),
                    "entry_count": 0,
                    "source_provenance": data.get("source_provenance", "unknown"),
                    "license": "Unknown",
                    "semantic_vector_assets": data.get("semantic_vector_assets", []),
                    "dependencies": data.get("dependencies", [])
                }

                if 'header' in data and 'code' in data['header']:
                    pack_info["entry_count"] = len(data.get('domains', []))
                    pack_info["license"] = data['header'].get('license', 'Unknown')
                    pack_info["language"] = data['header']['code']
                    expected_count = data['header'].get('terms_count')
                    if expected_count is not None and expected_count != pack_info["entry_count"]:
                         raise ManifestBuilderError(f"Mismatched entry count in {filepath}: header says {expected_count}, actual is {pack_info['entry_count']}")

                elif 'terms_count' in data:
                    pack_info["entry_count"] = data['terms_count']
                    pack_info["license"] = data.get('license', 'Unknown')
                    pack_info["language"] = data.get('lang_code', 'Unknown')
                    if 'items' in data and len(data['items']) != pack_info["entry_count"]:
                        raise ManifestBuilderError(f"Mismatched entry count in {filepath}")
                    if 'vocabulary' in data and len(data['vocabulary']) != pack_info["entry_count"]:
                        raise ManifestBuilderError(f"Mismatched entry count in {filepath}")

                else:
                    pack_info["language"] = data.get("language", "Unknown")
                    if 'vocabulary' in data:
                        pack_info["entry_count"] = len(data['vocabulary'])
                    elif 'items' in data:
                        pack_info["entry_count"] = len(data['items'])

                if pack_info["entry_count"] == 0:
                     raise ManifestBuilderError(f"No entries found in {filepath}")

                return pack_info

        except (gzip.BadGzipFile, json.JSONDecodeError) as e:
            raise ManifestBuilderError(f"Failed to parse {filepath}: {e}")

    def generate_manifest(self, output_file="manifest_new.json"):
        manifest = {
            "schemaVersion": self.schema_version,
            "packs": {}
        }

        try:
            for filename in sorted(os.listdir(self.packs_dir)):
                if not filename.endswith(".pack.gz"):
                    continue
                filepath = os.path.join(self.packs_dir, filename)
                safe_path = self._safe_path(filepath)

                size, sha256 = self.sha256_file(safe_path)
                pack_info = self._extract_pack_info(safe_path)

                manifest["packs"][filename] = {
                    "pack_id": pack_info["pack_id"],
                    "language": pack_info["language"],
                    "schema_version": pack_info["schema_version"],
                    "entry_count": pack_info["entry_count"],
                    "size_bytes": size,
                    "sha256": sha256,
                    "source_provenance": pack_info["source_provenance"],
                    "license": pack_info["license"],
                    "semantic_vector_assets": pack_info["semantic_vector_assets"],
                    "dependencies": pack_info["dependencies"]
                }

            # Check for broken dependencies
            for pack_id, pack_data in manifest["packs"].items():
                for dep in pack_data["dependencies"]:
                    if dep not in manifest["packs"]:
                        raise ManifestBuilderError(f"Broken dependency: {pack_id} depends on {dep} which is missing")

            manifest_str = json.dumps(manifest, indent=2, sort_keys=True)
            if len(manifest_str.encode('utf-8')) > self.max_manifest_size:
                 raise ManifestBuilderError("Manifest size exceeds limit")

            # Atomic write
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(output_file)))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(manifest_str)
                os.replace(temp_path, output_file)
            except Exception:
                os.remove(temp_path)
                raise

            return manifest

        except Exception as e:
            raise ManifestBuilderError(f"Manifest generation failed: {e}")


class UpdatePlanGenerator:
    def compare_manifests(self, old_manifest, new_manifest):
        """
        Compares two manifests to identify safe daily content changes
        without repackaging unchanged language assets.
        Skips unchanged packs and changed metadata with no payload delta.
        """
        plan = {
            "to_update": [],
            "to_remove": [],
            "to_add": [],
            "unchanged": [],
            "metadata_only_changes": []
        }

        old_packs = old_manifest.get("packs", {})
        new_packs = new_manifest.get("packs", {})

        for pack_id, new_data in new_packs.items():
            if pack_id not in old_packs:
                plan["to_add"].append(pack_id)
                continue

            old_data = old_packs[pack_id]

            # Check for pure metadata changes without payload/content delta
            # In context of the objective: "changed metadata with no payload delta"
            payload_changed = (
                old_data["sha256"] != new_data["sha256"] or
                old_data["entry_count"] != new_data["entry_count"] or
                old_data["size_bytes"] != new_data["size_bytes"]
            )

            # Other logical metadata properties (like schema version, license)
            metadata_changed = (
                old_data["language"] != new_data["language"] or
                old_data["schema_version"] != new_data["schema_version"] or
                old_data["source_provenance"] != new_data["source_provenance"] or
                old_data["license"] != new_data["license"] or
                old_data["semantic_vector_assets"] != new_data["semantic_vector_assets"] or
                old_data["dependencies"] != new_data["dependencies"]
            )

            if not payload_changed:
                if metadata_changed:
                    plan["metadata_only_changes"].append(pack_id)
                else:
                    plan["unchanged"].append(pack_id)
            else:
                plan["to_update"].append(pack_id)

        for pack_id in old_packs:
            if pack_id not in new_packs:
                plan["to_remove"].append(pack_id)

        return plan
