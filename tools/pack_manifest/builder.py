import json
import hashlib
from pathlib import Path
import os
import gzip
import base64
import sys
import tempfile

# Append the repository root to sys.path to allow importing tools modules
repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

MAX_MANIFEST_SIZE = 10 * 1024 * 1024 # 10MB limit

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def is_safe_path(path: Path, base_dir: Path) -> bool:
    try:
        return path.resolve().is_relative_to(base_dir.resolve())
    except Exception:
        return False

def build_manifest(pack_id: str, pack_path: Path, base_dir: Path = None) -> dict:
    if not pack_path.is_file():
        raise ValueError(f"Missing pack file: {pack_path}")

    if base_dir and not is_safe_path(pack_path, base_dir):
        raise ValueError("Directory traversal attempt rejected")

    try:
        from tools.pack_v2.pipeline import MAX_ENVELOPE, FILES
    except ImportError:
        # Fallback constants if needed
        MAX_ENVELOPE = 120 * 1024 * 1024
        FILES = ('content/content.json', 'content/content.sqlite', 'metadata/pack.json')

    pack_size = pack_path.stat().st_size
    # We should bound decompressed data instead, using read limits

    try:
        with gzip.open(pack_path, 'rt', encoding='utf-8') as f:
            envelope_str = f.read(MAX_ENVELOPE + 1)
            if len(envelope_str) > MAX_ENVELOPE:
                 raise ValueError("Pack decompressed data exceeds limit")
            envelope = json.loads(envelope_str)
    except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Invalid pack format: {e}")

    if envelope.get('schemaVersion') != "2.0.0":
         raise ValueError("envelope identity/version mismatch")

    rows = envelope.get('files')
    if not isinstance(rows, list) or len(rows) != len(FILES) or {i.get('path') for i in rows} != set(FILES):
         raise ValueError("mandatory envelope file missing/duplicate")

    content = {}
    for item in rows:
        content[item['path']] = base64.b64decode(item['contentBase64'], validate=True)

    metadata = json.loads(content['metadata/pack.json'])
    content_info = json.loads(content['content/content.json'])

    # Requirement 8: reject mismatched entry counts
    if metadata.get('contentRows') != content_info.get('tableCounts', {}).get('lexicon', 0):
         raise ValueError("Mismatched entry counts in pack")

    # We should return the minimal update identity with the required fields
    return {
        "packId": metadata.get("packId", pack_id),
        "languageCode": metadata.get("languageCode"),
        "schemaVersion": metadata.get("schemaVersion"),
        "version": metadata.get("version"),
        "contentRows": metadata.get("contentRows"),
        "contentSha256": metadata.get("contentSha256"),
        "artifactSizeBytes": pack_size,
        "artifactSha256": file_sha256(pack_path),
        "sourceIds": metadata.get("sourceIds", []),
        "licenses": metadata.get("licenses", content_info.get("licenses", [])), # Ensure licenses are tracked
        "fixtureOnly": metadata.get("fixtureOnly", False),
        "dependencies": metadata.get("dependencies", []) # For semantic-vector asset pack references
    }

def generate_update_plan(old_manifest_data: dict, new_manifest_data: dict) -> dict:
    plan = {
        "added": [],
        "updated": [],
        "removed": [],
        "unchanged": [],
        "broken_dependencies": []
    }

    old_packs = {p["packId"]: p for p in old_manifest_data.get("packs", [])}
    new_packs = {p["packId"]: p for p in new_manifest_data.get("packs", [])}

    for pack_id, new_pack in new_packs.items():
        if pack_id not in old_packs:
            plan["added"].append(pack_id)
        else:
            old_pack = old_packs[pack_id]
            # Skip changed metadata with no payload delta
            if new_pack["contentSha256"] != old_pack["contentSha256"]:
                plan["updated"].append(pack_id)
            else:
                plan["unchanged"].append(pack_id)

        # Check dependencies
        for dep in new_pack.get("dependencies", []):
            if dep not in new_packs:
                plan["broken_dependencies"].append({"pack": pack_id, "missing_dependency": dep})

    for pack_id in old_packs:
        if pack_id not in new_packs:
            plan["removed"].append(pack_id)

    return plan

def create_manifest(packs_dir: Path, output_file: Path):
    if not packs_dir.is_dir():
         raise ValueError(f"Missing packs dir: {packs_dir}")

    manifest_data = {"packs": []}

    for item in sorted(packs_dir.glob("*.pack.gz")):
         pack_id = item.name.split('.')[0]
         # Removing version from pack_id
         if '-' in pack_id and len(pack_id.split('-')[-1].split('.')) == 3: # 1.0.0
            pack_id = '-'.join(pack_id.split('-')[:-1])

         manifest_data["packs"].append(build_manifest(pack_id, item, packs_dir))

    json_str = json.dumps(manifest_data, indent=2)
    if len(json_str) > MAX_MANIFEST_SIZE:
         raise ValueError("Generated manifest exceeds maximum size limit")

    with tempfile.NamedTemporaryFile('w', dir=output_file.parent, delete=False) as f:
         f.write(json_str)
         tmp_name = f.name

    os.replace(tmp_name, output_file)
