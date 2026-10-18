"""Synthetic, temporary *test-only* evidence; never a production source ledger."""
import hashlib
import json
from pathlib import Path

def put(root, name, value):
    p = Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(value)
    return hashlib.sha256(value).hexdigest()

def fixture(root, source_id="case-source"):
    origin = "https://example.org/fixture-source"
    original_sha = put(root, "evidence/upstream.bin", b"source fixture bytes")
    rights_sha = put(root, "evidence/rights.txt", b"Test author grants CC0 to fixture data")
    source = {
        "source_id": source_id, "kind": "dictionary", "origin_url": origin,
        "publisher": "Example Test Publisher", "author": "Test Author",
        "dataset_version": "1.0",
        "retrieval": {"identity": "test-capture", "url": origin, "date": "2026-10-12",
                      "artifact_path": "evidence/upstream.bin", "sha256": original_sha},
        "license": {"id": "CC0-1.0", "evidence_url": origin + "/rights",
                    "evidence_path": "evidence/rights.txt", "evidence_sha256": rights_sha},
        "status": "APPROVED_FOR_REDISTRIBUTION",
        "review": {"reviewer": "fixture-reviewer", "decision_url": origin + "/review"},
        "alterations": ["no changes"]
    }
    ledger = {"schema_version": "1.0.0", "sources": [source]}
    save_ledger(root, ledger)
    return ledger, source

def ref(source):
    return {"source_id": source["source_id"],
            "dataset_version": source["dataset_version"],
            "artifact_sha256": source["retrieval"]["sha256"]}

def save_ledger(root, ledger):
    p = Path(root) / "legal/ledger/sources.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ledger), encoding="utf-8")
    return p
