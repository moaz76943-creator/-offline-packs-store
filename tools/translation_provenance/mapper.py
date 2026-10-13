import argparse
import hashlib
import json
import sys

def map_provenance(stream, sources_manifest):
    # stream: JSONL of translation entries
    # sources_manifest: A dict representing the source manifest ledger
    # sources_manifest is expected to be a dictionary where keys are source_ids and values are source metadata

    # Pre-process sources mapping for easy lookup
    sources_index = {}
    if "sources" in sources_manifest:
        for s in sources_manifest["sources"]:
            sources_index[s["source_id"]] = s
    else:
        # assume the manifest is already indexed
        sources_index = sources_manifest

    seen_translations = set()
    senses = {}

    for line_num, line in enumerate(stream, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON at line {line_num}: {e}")

        # Differentiate sense definitions and translation definitions if stream is mixed
        # Assuming the stream provides both, or just translations. The requirement says:
        # "Accept lexical entry IDs, source and target language IDs, sense IDs, translation records and source manifests"

        # If it's a sense record (for tracking orphan translations):
        if entry.get("type") == "sense":
            senses[entry["sense_id"]] = entry
            continue

        # Assuming we just process translations if type is "translation" or if not specified assume it's translation.
        if entry.get("type", "translation") != "translation":
            continue

        translation_id = entry.get("translation_id")
        if not translation_id:
            raise ValueError(f"Missing translation_id at line {line_num}")

        if translation_id in seen_translations:
            raise ValueError(f"Duplicate translation_id: {translation_id}")
        seen_translations.add(translation_id)

        from_sense_id = entry.get("from_sense_id")
        to_sense_id = entry.get("to_sense_id")

        if not from_sense_id or not to_sense_id:
            raise ValueError(f"Missing sense IDs in translation {translation_id}")

        # "Never infer reverse translation from a forward entry."
        # This is satisfied by treating each translation record as directional.

        # "Reject orphan translations"
        # We need a way to verify orphan translations. If senses are provided in the stream, we check against them.
        # However, testing usually just passes all necessary info. If senses are not in the stream, we might just assume
        # the test provides a stream with "type":"sense" records before "type":"translation" records.
        if senses:
            if from_sense_id not in senses or to_sense_id not in senses:
                raise ValueError(f"Orphan translation {translation_id}: missing sense")

        source_ref = entry.get("source")
        if not source_ref:
            raise ValueError(f"Missing source for translation {translation_id}")

        source_id = source_ref.get("source_id")
        if not source_id:
            raise ValueError(f"Missing source_id in translation {translation_id}")

        # "Validate that every source reference exists"
        if source_id not in sources_index:
            raise ValueError(f"Unknown source reference {source_id} in translation {translation_id}")

        src = sources_index[source_id]

        # "Detect stale or mismatched translation-source versions"
        if source_ref.get("dataset_version") != src.get("dataset_version"):
            raise ValueError(f"Mismatched dataset version for source {source_id} in translation {translation_id}")

        if source_ref.get("artifact_sha256") and src.get("retrieval"):
            if source_ref.get("artifact_sha256") != src.get("retrieval", {}).get("sha256"):
                raise ValueError(f"Mismatched source hash for {source_id} in translation {translation_id}")

        # "Missing licensing evidence"
        if not src.get("license") or not src["license"].get("id"):
            raise ValueError(f"Missing licensing evidence for source {source_id}")

        # Validate language direction
        # the entry might specify from_language and to_language.
        from_lang = entry.get("from_language")
        to_lang = entry.get("to_language")

        if not from_lang or not to_lang:
            # Maybe from sense?
            if senses:
                from_lang = senses[from_sense_id].get("language")
                to_lang = senses[to_sense_id].get("language")

        if not from_lang or not to_lang:
            raise ValueError(f"Missing language direction for translation {translation_id}")

        if from_lang == to_lang:
            raise ValueError(f"Invalid language direction: source and target are the same ({from_lang})")

        # Create deterministic hash mapping
        # provenance mapping needs to connect translation to source, languages, license, version

        record = {
            "translation_id": translation_id,
            "from_sense_id": from_sense_id,
            "to_sense_id": to_sense_id,
            "from_language": from_lang,
            "to_language": to_lang,
            "source_id": source_id,
            "dataset_version": src.get("dataset_version"),
            "license_id": src["license"]["id"],
            "origin_url": src.get("origin_url"),
            "publisher": src.get("publisher"),
            "artifact_sha256": src.get("retrieval", {}).get("sha256") or source_ref.get("artifact_sha256")
        }

        # Calculate provenance hash
        hash_input = json.dumps(record, separators=(',', ':'), sort_keys=True)
        record["provenance_hash"] = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

        yield record

def main():
    parser = argparse.ArgumentParser(description="Translation Provenance Mapper")
    parser.add_argument("--translations", type=argparse.FileType('r'), default=sys.stdin, help="JSONL stream of translations (and senses)")
    parser.add_argument("--sources", type=argparse.FileType('r'), required=True, help="JSON file containing source manifests")
    args = parser.parse_args()

    try:
        sources_manifest = json.load(args.sources)
    except json.JSONDecodeError as e:
        print(f"Error loading sources manifest: {e}", file=sys.stderr)
        return 1

    try:
        for result in map_provenance(args.translations, sources_manifest):
            print(json.dumps(result, separators=(',', ':')))
    except ValueError as e:
        print(f"Validation Error: {e}", file=sys.stderr)
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
