"""Source-accurate attribution output; never approves redistribution."""
import argparse
import json
from pathlib import Path

from tools.contribution_gate.evidence import (
    exact_source_reference, verified_sources
)

def generate_attribution(ledger_path, refs_path, out_dir, *, repo_root=None):
    if repo_root is None:
        raise ValueError("repo_root required to verify original evidence bytes")
    ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    sources = verified_sources(ledger, repo_root)
    refs = json.loads(Path(refs_path).read_text(encoding="utf-8"))
    if not isinstance(refs, list) or not refs:
        raise ValueError("Nonempty source references required")
    unique = set()
    records = []
    # Validate the *complete* batch before writing a single file.
    for ref in refs:
        source = exact_source_reference(ref, sources)
        sid = source["source_id"]
        if sid in unique:
            raise ValueError("Duplicate source reference " + sid)
        unique.add(sid)
        records.append({
            "source_id": sid, "publisher": source["publisher"],
            "origin_url": source["origin_url"], "dataset_version": source["dataset_version"],
            "artifact_sha256": source["retrieval"]["sha256"],
            "retrieval_identity": source["retrieval"]["identity"],
            "retrieval_url": source["retrieval"]["url"],
            "license_id": source["license"]["id"],
            "license_evidence_url": source["license"]["evidence_url"],
            "license_evidence_sha256": source["license"]["evidence_sha256"],
            "alterations": source["alterations"],
            "review": source["review"],
            "public_domain_proof": source["license"].get("public_domain_proof"),
            "notice_file": sid + "_notice.txt"
        })
    records.sort(key=lambda r: r["source_id"])
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for r in records:
        notice = "\n".join([
            "Source: " + r["source_id"],
            "Publisher: " + r["publisher"],
            "Origin: " + r["origin_url"],
            "Version: " + r["dataset_version"],
            "Retrieved snapshot: " + r["retrieval_identity"],
            "Snapshot SHA-256: " + r["artifact_sha256"],
            "License: " + r["license_id"],
            "Source-specific rights: " + r["license_evidence_url"],
            "Rights proof SHA-256: " + r["license_evidence_sha256"],
            "Alterations: " + "; ".join(r["alterations"]),
            "Independent review: " + r["review"]["reviewer"] + " " + r["review"]["decision_url"],
            "Public-domain basis: " + json.dumps(r["public_domain_proof"], sort_keys=True)
        ]) + "\n"
        (output / r["notice_file"]).write_text(notice, encoding="utf-8")
    (output / "attribution.json").write_text(
        json.dumps(records, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return records

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--refs", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        generate_attribution(args.ledger, args.refs, args.out_dir, repo_root=args.repo_root)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(1, "BLOCKED: " + str(exc) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
