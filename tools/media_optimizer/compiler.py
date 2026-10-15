import json
import zlib
import hashlib
import os
import shutil

class ValidationError(Exception):
    pass

class MediaPackCompiler:
    MAX_FILE_SIZE = 2048
    MAX_PATHS = 50
    SUPPORTED_VERSIONS = {1}
    SUPPORTED_LICENSES = {"CC0-1.0", "PUBLIC-DOMAIN"}

    def __init__(self, decoder_evidence_provided=False):
        self.decoder_evidence_provided = decoder_evidence_provided

    def _read_and_validate(self, filepath):
        if os.path.getsize(filepath) >= self.MAX_FILE_SIZE:
            raise ValidationError(f"File {filepath} exceeds {self.MAX_FILE_SIZE} bytes.")

        try:
            with open(filepath, 'rb') as f:
                compressed_data = f.read()
        except OSError as e:
            raise ValidationError(f"Failed to read file {filepath}: {e}")

        try:
            uncompressed_data = zlib.decompress(compressed_data)
        except zlib.error as e:
            raise ValidationError(f"Invalid zlib stream in {filepath}: {e}")

        try:
            canonical_json = json.dumps(json.loads(uncompressed_data.decode('utf-8')), separators=(',', ':'), sort_keys=True)
            data = json.loads(canonical_json)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValidationError(f"Invalid JSON in {filepath}: {e}")

        if "version" not in data or data["version"] not in self.SUPPORTED_VERSIONS:
            raise ValidationError(f"Unsupported or missing version in {filepath}")

        if "license" not in data or data["license"] not in self.SUPPORTED_LICENSES:
            raise ValidationError(f"Unsupported or missing license in {filepath}")

        if "id" not in data:
            raise ValidationError(f"Missing concept id in {filepath}")

        paths = data.get("paths", [])
        if not isinstance(paths, list) or len(paths) > self.MAX_PATHS:
            raise ValidationError(f"Invalid or too many paths in {filepath}")

        # Basic geometry validation
        for p in paths:
            if not isinstance(p, str):
                raise ValidationError(f"Malformed geometry in {filepath}")

        source_hash = hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

        return {
            "id": data["id"],
            "version": data["version"],
            "license": data["license"],
            "paths": paths,
            "hash": source_hash,
            "canonical_json": canonical_json,
            "label": data.get("label", data["id"])
        }

    def build_pack(self, token_paths, output_dir, previous_pack_path=None):
        if not self.decoder_evidence_provided:
            raise ValidationError("Cannot build production-ready pack without decoder compatibility evidence.")

        tokens = []
        for path in sorted(token_paths):
            tokens.append(self._read_and_validate(path))

        # Deduplicate geometry
        geometry_pool = {}
        geometry_index = {}

        concept_lookup = {}

        for t in tokens:
            # We use the canonical JSON representation of paths as the deduplication key
            geom_key = json.dumps(t["paths"], separators=(',', ':'))
            if geom_key not in geometry_index:
                geom_id = f"geom_{len(geometry_index)}"
                geometry_index[geom_key] = geom_id
                geometry_pool[geom_id] = t["paths"]

            geom_id = geometry_index[geom_key]
            concept_lookup[t["id"]] = {
                "geom_id": geom_id,
                "version": t["version"],
                "hash": t["hash"],
                "label": t["label"]
            }

        pack_content = {
            "geometry_pool": geometry_pool,
            "concepts": concept_lookup
        }

        pack_json = json.dumps(pack_content, separators=(',', ':'), sort_keys=True)
        pack_hash = hashlib.sha256(pack_json.encode('utf-8')).hexdigest()

        delta_plan = {"added": [], "updated": [], "removed": []}
        j087_events = []

        if previous_pack_path and os.path.exists(previous_pack_path):
            try:
                with open(previous_pack_path, 'r', encoding='utf-8') as f:
                    prev_pack = json.load(f)
                    prev_concepts = prev_pack.get("concepts", {})

                    for cid, cdata in concept_lookup.items():
                        if cid not in prev_concepts:
                            delta_plan["added"].append(cid)
                            j087_events.append({"type": "ADDED", "id": cid, "hash": cdata["hash"]})
                        elif prev_concepts[cid]["hash"] != cdata["hash"]:
                            delta_plan["updated"].append(cid)
                            j087_events.append({"type": "UPDATED", "id": cid, "hash": cdata["hash"]})

                    for cid in prev_concepts:
                        if cid not in concept_lookup:
                            delta_plan["removed"].append(cid)
                            j087_events.append({"type": "REMOVED", "id": cid})
            except Exception:
                pass
        else:
            for cid, cdata in concept_lookup.items():
                delta_plan["added"].append(cid)
                j087_events.append({"type": "ADDED", "id": cid, "hash": cdata["hash"]})

        metadata = {
            "sha256": pack_hash,
            "actual_size": len(pack_json.encode('utf-8')),
            "delta_plan": delta_plan,
            "j087_events": j087_events
        }

        wordbit_manifest = {
            "decoder_version": 1,
            "max_paths": self.MAX_PATHS,
            "supported_encodings": list(self.SUPPORTED_VERSIONS)
        }

        os.makedirs(output_dir, exist_ok=True)
        pack_out_path = os.path.join(output_dir, "pack.json")
        temp_pack_path = os.path.join(output_dir, "pack.json.tmp")

        try:
            with open(temp_pack_path, 'w', encoding='utf-8') as f:
                f.write(pack_json)

            # Atomic move
            shutil.move(temp_pack_path, pack_out_path)

            with open(os.path.join(output_dir, "metadata.json"), 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, sort_keys=True)

            with open(os.path.join(output_dir, "wordbit_manifest.json"), 'w', encoding='utf-8') as f:
                json.dump(wordbit_manifest, f, indent=2, sort_keys=True)

        except (OSError, MemoryError) as e:
            if os.path.exists(temp_pack_path):
                os.remove(temp_pack_path)
            raise e

        return metadata
