"""Read-only adapter for the canonical legal/ledger admission contract.

An evidence check is not a legal opinion, rights grant or publication approval.
"""
import json
import re
from pathlib import Path

from legal.ledger.admission import HASH, artifact, evaluate, text, url_ok

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

def required(value, label):
    if not text(value):
        raise ValueError("Missing " + label)
    return value

def verified_sources(ledger, repo_root):
    if repo_root is None:
        raise ValueError("Missing repo_root for offline verification")
    if not isinstance(ledger, dict) or ledger.get("schema_version") != "1.0.0":
        raise ValueError("Invalid canonical ledger schema")
    # Never trust a caller-crafted ledger in place of the canonical source registry.
    root = Path(repo_root).resolve()
    canonical_path = root / "legal/ledger/sources.json"
    if (not canonical_path.is_file() or canonical_path.is_symlink() or
            not canonical_path.resolve().is_relative_to(root)):
        raise ValueError("Missing or escaping canonical source ledger")
    try:
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Malformed canonical source ledger") from exc
    if canonical != ledger:
        raise ValueError("Caller source manifest contradicts canonical legal/ledger/sources.json")
    entries = ledger.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError("No verified canonical source records")
    ids = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str):
            raise ValueError("Malformed source record")
        sid = item["source_id"]
        if not SAFE_ID.fullmatch(sid) or item.get("synthetic") is True or sid.startswith(("fixture-", "test-")):
            raise ValueError("Unsafe or synthetic source identity")
        ids.append(sid)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate source identities")
    errors = evaluate(ledger, {"languages": [], "packs": []}, [], Path(repo_root))
    if errors:
        raise ValueError("Ledger evidence rejected: " + "; ".join(errors))
    return {item["source_id"]: item for item in entries}

def load_verified_ledger(repo_root):
    if repo_root is None:
        raise ValueError("Missing repo_root")
    root = Path(repo_root).resolve()
    path = root / "legal/ledger/sources.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing canonical ledger file")
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Unreadable canonical ledger") from exc
    return verified_sources(ledger, root)

def exact_source_reference(ref, sources):
    if not isinstance(ref, dict):
        raise ValueError("Missing source reference")
    sid = required(ref.get("source_id"), "source_id")
    if sid not in sources:
        raise ValueError("Unknown source_id: " + sid)
    src = sources[sid]
    if not text(ref.get("dataset_version")) or ref["dataset_version"] != src["dataset_version"]:
        raise ValueError("Missing or stale dataset_version: " + sid)
    sha = ref.get("artifact_sha256")
    if not isinstance(sha, str) or not HASH.fullmatch(sha) or sha != src["retrieval"]["sha256"]:
        raise ValueError("Missing, malformed or conflicting source hash: " + sid)
    return src

def verified_artifact(root, path, sha, label):
    errors = []
    if not artifact(root, path, sha, errors, label):
        raise ValueError("; ".join(errors))
    return path
