import argparse
import json
import sys
from pathlib import Path

def generate_attribution(ledger_path: Path, refs_path: Path, out_dir: Path):
    with open(ledger_path, 'r', encoding='utf-8') as f:
        ledger_data = json.load(f)

    if "sources" in ledger_data:
        # Array of sources format
        sources = {s["source_id"]: s for s in ledger_data.get("sources", [])}
    else:
        # dict format? Schema says: {"schema_version": "1.0.0", "sources": [{"source_id": ...}]}
        sources = {}

    with open(refs_path, 'r', encoding='utf-8') as f:
        refs_data = json.load(f)

    if not isinstance(refs_data, list):
        print("Error: refs must be a JSON array.", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    machine_readable = []

    for ref in refs_data:
        source_id = ref.get("source_id")
        if not source_id:
            print("Error: missing source_id in ref.", file=sys.stderr)
            sys.exit(1)

        if source_id not in sources:
            print(f"Error: source_id '{source_id}' not found in ledger.", file=sys.stderr)
            sys.exit(1)

        src = sources[source_id]

        # Verify matching version and hash
        ref_version = ref.get("dataset_version")
        if ref_version != src.get("dataset_version"):
            print(f"Error: changed source version for '{source_id}'. Expected {src.get('dataset_version')}, got {ref_version}.", file=sys.stderr)
            sys.exit(1)

        ref_hash = ref.get("artifact_sha256")
        src_hash = src.get("retrieval", {}).get("sha256")
        if ref_hash != src_hash:
            print(f"Error: conflicting artifact hash for '{source_id}'. Expected {src_hash}, got {ref_hash}.", file=sys.stderr)
            sys.exit(1)

        # Verify approval
        if src.get("status") != "APPROVED_FOR_REDISTRIBUTION":
            print(f"Error: source '{source_id}' is not approved for redistribution.", file=sys.stderr)
            sys.exit(1)

        # Verify required metadata (missing authors, URLs, etc.)
        publisher = src.get("publisher")
        if not publisher:
            print(f"Error: missing publisher (author) for '{source_id}'.", file=sys.stderr)
            sys.exit(1)

        origin_url = src.get("origin_url")
        if not origin_url:
            print(f"Error: missing origin_url for '{source_id}'.", file=sys.stderr)
            sys.exit(1)

        license_info = src.get("license", {})
        license_id = license_info.get("id")
        if not license_id:
            print(f"Error: missing license for '{source_id}'.", file=sys.stderr)
            sys.exit(1)

        # Generate notice
        lines = []
        lines.append(f"Source: {source_id}")
        lines.append(f"Publisher: {publisher}")
        lines.append(f"URL: {origin_url}")
        lines.append(f"Version: {ref_version}")
        lines.append(f"License: {license_id}")
        lines.append(f"Artifact Hash: {ref_hash}")

        alterations = src.get("alterations", [])
        if alterations and any(a for a in alterations if a.strip() and a != "none"):
            lines.append("\nModifications:")
            for alt in alterations:
                lines.append(f"- {alt}")

        if license_id == "PUBLIC-DOMAIN":
            pd_proof = license_info.get("public_domain_proof", {})
            if pd_proof:
                lines.append("\nPublic Domain Proof:")
                lines.append(f"Jurisdiction: {pd_proof.get('jurisdiction')}")
                lines.append(f"Legal Basis: {pd_proof.get('legal_basis')}")
                lines.append(f"Work Date: {pd_proof.get('work_date')}")

        notice_text = "\n".join(lines) + "\n"
        notice_path = out_dir / f"{source_id}_notice.txt"
        with open(notice_path, "w", encoding="utf-8") as f:
            f.write(notice_text)

        # Add to machine readable
        machine_readable.append({
            "source_id": source_id,
            "publisher": publisher,
            "origin_url": origin_url,
            "dataset_version": ref_version,
            "artifact_sha256": ref_hash,
            "license_id": license_id,
            "alterations": alterations,
            "notice_file": f"{source_id}_notice.txt",
            "public_domain_proof": license_info.get("public_domain_proof")
        })

    # Sort machine_readable for stability
    machine_readable.sort(key=lambda x: x["source_id"])

    with open(out_dir / "attribution.json", "w", encoding="utf-8") as f:
        json.dump(machine_readable, f, indent=2, sort_keys=True)
        f.write("\n")

def main():
    parser = argparse.ArgumentParser(description="Deterministic Open Attribution Generator")
    parser.add_argument("--ledger", type=Path, required=True, help="Path to ledger sources.json")
    parser.add_argument("--refs", type=Path, required=True, help="Path to JSON containing an array of source references")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory to output notices")
    args = parser.parse_args()

    generate_attribution(args.ledger, args.refs, args.out_dir)

if __name__ == "__main__":
    main()
