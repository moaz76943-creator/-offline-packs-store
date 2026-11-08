import argparse
import json
import os
import sys
import hashlib
from typing import TextIO, Any

def install_repo_import_path(repo_root: str):
    if not os.access(repo_root, os.R_OK | os.X_OK):
        raise RuntimeError(f"Repository root '{repo_root}' is inaccessible.")
    sys.path.insert(0, os.path.abspath(repo_root))

def get_record_hash(record_str: str) -> str:
    """Returns the SHA-256 hash of the record string."""
    return hashlib.sha256(record_str.encode('utf-8')).hexdigest()

# streaming validation CLI
def process_stream(
    input_stream: TextIO,
    accept_stream: TextIO,
    repair_stream: TextIO,
    quarantine_stream: TextIO,
    review_stream: TextIO,
    quarantine_dir: str,
    engine: 'Any'
):
    """Processes a JSONL stream line by line, writing to appropriate output streams."""
    os.makedirs(quarantine_dir, exist_ok=True)

    stats = {
        "total": 0,
        "accept": 0,
        "repairable": 0,
        "quarantine": 0,
        "review_required": 0,
        "broken_json": 0
    }

    for line in input_stream:
        line = line.strip()
        if not line:
            continue

        stats["total"] += 1

        # Keep original string for hash
        record_hash = get_record_hash(line)

        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            stats["broken_json"] += 1
            stats["quarantine"] += 1
            # Broken JSON is automatically quarantined
            reason = f"Broken JSON: {e}"
            quarantine_stream.write(line + "\n")

            # Save reason to file
            reason_path = os.path.join(quarantine_dir, f"{record_hash}.reason.txt")
            with open(reason_path, 'w', encoding='utf-8') as rf:
                rf.write(f"Hash: {record_hash}\nReason: {reason}\n")
            continue

        status, processed_record, reason = engine.validate_and_repair(record)

        if status == "ACCEPT":
            stats["accept"] += 1
            accept_stream.write(json.dumps(processed_record, ensure_ascii=False) + "\n")

        elif status == "REPAIRABLE":
            stats["repairable"] += 1
            repair_stream.write(json.dumps(processed_record, ensure_ascii=False) + "\n")
            # Also output repaired to accept stream per typical pipeline
            accept_stream.write(json.dumps(processed_record, ensure_ascii=False) + "\n")

        elif status == "QUARANTINE":
            stats["quarantine"] += 1
            quarantine_stream.write(line + "\n")

            # Save reason to file
            reason_path = os.path.join(quarantine_dir, f"{record_hash}.reason.txt")
            with open(reason_path, 'w', encoding='utf-8') as rf:
                rf.write(f"Hash: {record_hash}\nReason: {reason}\n")

        elif status == "REVIEW_REQUIRED":
            stats["review_required"] += 1
            review_stream.write(line + "\n")

    return stats

def main():
    parser = argparse.ArgumentParser(description="Multilingual Lexicon Sanitizer & Deduplication Engine")
    parser.add_argument("--input", required=True, help="Input JSONL file")
    parser.add_argument("--output-dir", required=True, help="Output directory for processed files")
    parser.add_argument("--registry", default="catalog/language_registry.v1.json", help="Path to language registry JSON")
    parser.add_argument("--repo-root", default=".", help="Path to the repository root directory")

    args = parser.parse_args()

    install_repo_import_path(args.repo_root)
    from tools.lexicon_sanitizer.engine import SanitizerEngine

    os.makedirs(args.output_dir, exist_ok=True)
    quarantine_dir = os.path.join(args.output_dir, "quarantined")

    accept_path = os.path.join(args.output_dir, "accept.jsonl")
    repair_path = os.path.join(args.output_dir, "repaired.jsonl")
    quarantine_path = os.path.join(args.output_dir, "quarantined.jsonl")
    review_path = os.path.join(args.output_dir, "review_required.jsonl")

    engine = SanitizerEngine(registry_path=args.registry)

    with open(args.input, "r", encoding="utf-8") as in_f, \
         open(accept_path, "w", encoding="utf-8") as acc_f, \
         open(repair_path, "w", encoding="utf-8") as rep_f, \
         open(quarantine_path, "w", encoding="utf-8") as quar_f, \
         open(review_path, "w", encoding="utf-8") as rev_f:

         stats = process_stream(
             input_stream=in_f,
             accept_stream=acc_f,
             repair_stream=rep_f,
             quarantine_stream=quar_f,
             review_stream=rev_f,
             quarantine_dir=quarantine_dir,
             engine=engine
         )

    print(json.dumps(stats, indent=2))

if __name__ == "__main__":
    main()
