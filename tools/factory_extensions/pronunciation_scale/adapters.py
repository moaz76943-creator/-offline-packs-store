"""Read-only adapters for pending PR #97 and PR #99; never assert production rights.

These adapters do not depend on pending Jules modules and do not merge their schemas.
"""
from __future__ import annotations
import hashlib
import json
from .factory import AuditError, VERSION, RECORD_LIMIT


def from_pr97(document: dict) -> dict:
    """Preserve PR97 source-specific readings without manufacturing audio or installed voices."""
    if document.get("registry_version") != "1.0.0" or not isinstance(document.get("records"), list):
        raise AuditError("unsupported PR97 registry")
    if len(document["records"]) > RECORD_LIMIT:
        raise AuditError("PR97 registry requires upstream sharding")
    result = []
    for record in document["records"]:
        if not isinstance(record, dict) or not all(record.get(x) for x in ("record_id", "lexeme_id", "language", "script")):
            raise AuditError("incomplete PR97 identity")
        for pron in record.get("pronunciations", []):
            src = pron.get("source") or {}
            if not all(src.get(k) for k in ("source_id", "publisher", "dataset_version", "record_locator", "license_id")):
                raise AuditError("missing per-reading PR97 source locator or rights")
            if not pron.get("notation") or not pron.get("value"):
                raise AuditError("unattested PR97 reading")
            reading = {"notation": pron["notation"], "value": pron["value"]}
            for key in ("stress", "dialect", "phonetic_note"):
                if pron.get(key):
                    reading[key] = pron[key]
            key = json.dumps([record["record_id"], reading], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stable = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            result.append({"pronunciation_id": f"{record['record_id']}:reading:{stable}",
                           "lexeme_id": record["lexeme_id"], "sense_id": record.get("sense_id"),
                           "language_id": record["language"], "language_tag": record.get("locale") or record["language"],
                           "script": record["script"], "variant_id": stable, "reading": reading,
                           "evidence": {k: src[k] for k in ("source_id", "publisher", "dataset_version", "record_locator", "license_id")},
                           "audio": []})
    if len(result) > RECORD_LIMIT or len({r["pronunciation_id"] for r in result}) != len(result):
        raise AuditError("duplicate or oversized PR97 readings")
    return {"metadata_version": VERSION, "records": sorted(result, key=lambda r: r["pronunciation_id"])}


def inspect_pr99(document: dict) -> dict:
    """PR99 record IDs/source hints are never enough for speaker-specific redistribution."""
    if not isinstance(document.get("assets"), list) or len(document["assets"]) > RECORD_LIMIT:
        raise AuditError("invalid or oversized PR99 audio manifest")
    return {"admitted": [], "quarantined": [
        {"record_id": a.get("record_id"), "source_id": (a.get("source") or {}).get("source_id"),
         "reason": "independent_audio_rights_and_speaker_review_required"}
        for a in document["assets"]]}
