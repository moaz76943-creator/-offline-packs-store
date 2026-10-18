"""Deterministic per-language coverage report; absent authorized evidence is zero."""
import argparse
import json
from pathlib import Path

from engine import EvidenceEngine, sha256


def compile_report(root):
    root = Path(root).resolve()
    engine = EvidenceEngine(root)
    admitted = [sid for sid in sorted(engine.sources) if engine.eligible_source(sid)]
    results = []
    base = Path("tools/linguistic_extensions/germanic_romance/shards")
    for code in sorted(engine.profiles):
        shard = base / (code + ".jsonl")
        found = (root / shard).is_file()
        results.append(engine.audit(code, str(shard) if found and admitted else None))
    return {
        "schema_version": "1.0.0",
        "registry_sha256": sha256(root / "catalog/language_registry.v1.json"),
        "ledger_sha256": sha256(root / "legal/ledger/sources.json"),
        "registered_profiles": len(results),
        "eligible_source_ids": admitted,
        "per_language": results,
        "totals": {key: sum(x[key] for x in results) for key in (
            "verified_verbs", "verified_paradigms", "verified_nouns", "verified_inflections")},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    args = p.parse_args()
    print(json.dumps(compile_report(args.root), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
