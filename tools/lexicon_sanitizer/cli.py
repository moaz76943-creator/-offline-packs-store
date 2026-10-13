import argparse
import json
import logging
import sys
import os
from pathlib import Path

from tools.lexicon_sanitizer.engine import (
    LexiconSanitizer,
    STATUS_ACCEPT,
    STATUS_REPAIRABLE,
    STATUS_QUARANTINE,
    STATUS_REVIEW_REQUIRED
)

logger = logging.getLogger(__name__)
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024

def stream_json_collections(file_path):
    """
    A custom, minimal streaming parser for top-level JSON arrays.
    """
    is_jsonl = str(file_path).endswith('.jsonl')
    if is_jsonl:
        with open(file_path, 'r', encoding='utf-8') as f:
            while True:
                line = f.readline(MAX_JSONL_LINE_BYTES + 1)
                if not line:
                    break
                if len(line.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
                    raise ValueError("JSONL record exceeds bounded size limit")
                if not line.strip():
                    continue
                yield "record", json.loads(line)
    else:
        # Stdlib json.load is NOT streaming: fail closed above an explicit cap.
        if Path(file_path).stat().st_size > MAX_JSON_BYTES:
            raise ValueError("Oversized JSON array: convert to bounded JSONL")
        with open(file_path, 'r', encoding='utf-8') as f:
            document = json.load(f)
            yield "metadata", {
                "contract_version": document.get("contract_version", "1.0.0"),
                "document_id": document.get("document_id", "doc")
            }
            for collection in ["lexemes", "senses", "translations", "examples", "relations"]:
                if collection in document:
                    for record in document[collection]:
                        yield collection, record

def process_file(input_path: Path, output_dir: Path, quarantine_dir: Path, workspace_path: Path):
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    sanitizer = LexiconSanitizer(workspace_path)

    out_file = output_dir / input_path.name
    quar_file = quarantine_dir / f"{input_path.stem}_quarantined.jsonl"
    if input_path.resolve() in (out_file.resolve(), quar_file.resolve()) or out_file.resolve() == quar_file.resolve():
        logger.error("Input and output/quarantine paths must be disjoint")
        sanitizer.close()
        return False
    tmp_out = out_file.with_name(out_file.name + ".pending")
    tmp_quar = quar_file.with_name(quar_file.name + ".pending")

    stats = {
        STATUS_ACCEPT: 0,
        STATUS_REPAIRABLE: 0,
        STATUS_QUARANTINE: 0,
        STATUS_REVIEW_REQUIRED: 0,
    }

    out_document = {
        "contract_version": "1.0.0",
        "document_id": "doc",
        "lexemes": [],
        "senses": [],
        "translations": [],
        "examples": [],
        "relations": []
    }

    is_jsonl = str(input_path).endswith('.jsonl')
    out_f = None
    if is_jsonl:
        out_f = open(tmp_out, 'w', encoding='utf-8')

    with open(tmp_quar, 'w', encoding='utf-8') as qf:
        try:
            for collection, record in stream_json_collections(input_path):
                if collection == "metadata":
                    out_document.update(record)
                    continue

                if collection == "record":
                    # For JSONL, we don't know the collection easily, guess from ID
                    if "sense_id" in record: collection = "senses"
                    elif "lexeme_id" in record: collection = "lexemes"
                    elif "translation_id" in record: collection = "translations"
                    elif "example_id" in record: collection = "examples"
                    elif "relation_id" in record: collection = "relations"
                    else: collection = "unknown"

                if collection == "lexemes":
                    status, modified, reason = sanitizer.sanitize_lexeme(record)
                elif collection == "senses":
                    status, modified, reason = sanitizer.sanitize_sense(record)
                elif collection == "translations":
                    status, modified, reason = sanitizer.sanitize_translation(record)
                elif collection in ["examples", "relations"]:
                    status, modified, reason = sanitizer.sanitize_generic(record, collection)
                else:
                    status, modified, reason = STATUS_QUARANTINE, record, "unknown record type"

                stats[status] = stats.get(status, 0) + 1

                if status in (STATUS_ACCEPT, STATUS_REPAIRABLE):
                    if is_jsonl:
                        out_f.write(json.dumps(modified, ensure_ascii=False) + '\n')
                    else:
                        out_document[collection].append(modified)

                    if status == STATUS_REPAIRABLE:
                        q_record = {
                            "status": status,
                            "reason": reason,
                            "collection": collection,
                            "hash": sanitizer.compute_hash(record),
                            "original": record
                        }
                        qf.write(json.dumps(q_record, ensure_ascii=True) + '\n')
                else:
                    q_record = {
                        "status": status,
                        "reason": reason,
                        "collection": collection,
                        "hash": sanitizer.compute_hash(record),
                        "original": record
                    }
                    qf.write(json.dumps(q_record, ensure_ascii=True) + '\n')
        except Exception as e:
            logger.error(f"Failed to process {input_path}: {e}")
            if is_jsonl:
                out_f.close()
            tmp_out.unlink(missing_ok=True)
            tmp_quar.unlink(missing_ok=True)
            sanitizer.close()
            return False

    if is_jsonl:
        out_f.close()
    else:
        with open(tmp_out, 'w', encoding='utf-8') as f:
            json.dump(out_document, f, ensure_ascii=False, indent=2)

    os.replace(tmp_out, out_file)
    os.replace(tmp_quar, quar_file)
    sanitizer.close()
    logger.info(f"Processed {input_path}. Stats: {stats}")
    return True

def main(argv=None):
    parser = argparse.ArgumentParser(description="Multilingual Lexicon Sanitizer")
    parser.add_argument("input", type=Path, nargs='+', help="Input JSON/JSONL file(s)")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for valid staged output")
    parser.add_argument("--quarantine-dir", type=Path, required=True, help="Directory for quarantined records")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Path to repository workspace")

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Workspace check
    manifest_path = args.workspace / "manifest.json"
    if not manifest_path.exists():
        logger.error("Public workspace is inaccessible (manifest.json not found). Stopping.")
        return 1

    success = True
    for input_file in args.input:
        if not process_file(input_file, args.output_dir, args.quarantine_dir, args.workspace):
            success = False

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
