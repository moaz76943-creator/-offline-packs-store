"""One synthetic ledger source for tests.

Hand-copied source dicts drift whenever schema.json or admission.evaluate gains
a field. Callers share this builder so that change is made once.

The result is a fixture. It is not an entry in legal/ledger/sources.json and it
is not a redistribution approval.
"""
import hashlib
from pathlib import Path

SOURCE_TEXT = "synthetic original fixture"
LICENSE_TEXT = "synthetic rights evidence fixture"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_source(root, *, source_id="synthetic_source", kind="pronunciation",
                     publisher="Synthetic publisher", author="synthetic-fixture",
                     dataset_version="v1", license_id="CC0-1.0"):
    """Return a schema-shaped source and write its two fixture files if absent."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "source.txt"
    license_path = root / "license.txt"
    if not source_path.exists():
        source_path.write_text(SOURCE_TEXT, encoding="utf-8")
    if not license_path.exists():
        license_path.write_text(LICENSE_TEXT, encoding="utf-8")
    return {
        "source_id": source_id,
        "kind": kind,
        "origin_url": "https://example.org/original",
        "publisher": publisher,
        "author": author,
        "dataset_version": dataset_version,
        "retrieval": {
            "identity": "fixture-snapshot-v1",
            "url": "https://example.org/original",
            "date": "2026-10-12",
            "artifact_path": "source.txt",
            "sha256": _sha(source_path),
        },
        "license": {
            "id": license_id,
            "evidence_url": "https://example.org/rights",
            "evidence_path": "license.txt",
            "evidence_sha256": _sha(license_path),
        },
        "status": "APPROVED_FOR_REDISTRIBUTION",
        "alterations": ["none"],
        "review": {"reviewer": "Fixture", "decision_url": "https://example.org/review"},
    }


def missing_required_fields(source, schema):
    """Required source keys from schema.json that this fixture omitted."""
    required = schema["$defs"]["source"]["required"]
    return [key for key in required if key not in source]
