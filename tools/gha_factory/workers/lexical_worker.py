#!/usr/bin/env python3
"""
Lexical Worker - Master Constitution Section 08 Compliant.
Parses lexical source records into structured (Term -> POS -> Gender -> Senses)
with strict Unicode NFC normalization. Guarantees senses are never flattened.
"""
import json
import os
import sys
import unicodedata

def normalize_text(text: str) -> str:
    if not text:
        return ""
    # NFC normalization standardizes precomposed vs decomposed umlauts and accents
    return unicodedata.normalize('NFC', text.strip())

def parse_lexical_record(raw_entry: dict, default_source_id: str = "kaikki_de_deu_core") -> dict:
    word = normalize_text(raw_entry.get('word', ''))
    pos = str(raw_entry.get('pos', 'unknown')).strip().lower()
    gender = raw_entry.get('gender')
    if gender:
        gender = str(gender).strip().lower()

    # Preserve distinct semantic senses as separate items
    raw_senses = raw_entry.get('senses', [])
    clean_senses = []
    if isinstance(raw_senses, list):
        for s in raw_senses:
            if isinstance(s, dict):
                gloss = s.get('gloss', s.get('definition', ''))
            else:
                gloss = str(s)
            normalized_gloss = normalize_text(gloss)
            if normalized_gloss:
                clean_senses.append(normalized_gloss)
    elif isinstance(raw_senses, str) and raw_senses.strip():
        clean_senses.append(normalize_text(raw_senses))

    return {
        'term': word,
        'pos': pos,
        'gender': gender,
        'senses': clean_senses,
        'source_id': raw_entry.get('source_id', default_source_id),
    }

def run_lexical_worker(source_snapshot_path: str, output_path: str):
    if not os.path.exists(source_snapshot_path):
        return False, f"SNAPSHOT_NOT_FOUND: {source_snapshot_path}", 0

    with open(source_snapshot_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    raw_entries = data.get('seed_entries', data.get('entries', []))
    parsed_lexicon = []

    for item in raw_entries:
        parsed = parse_lexical_record(item)
        if parsed['term'] and parsed['senses']:
            parsed_lexicon.append(parsed)

    if not parsed_lexicon:
        return False, "ZERO_YIELD: Parsed 0 valid lexical records", 0

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    payload = {
        'schema': 'polyglot_lexicon_v2',
        'entry_count': len(parsed_lexicon),
        'lexicon': parsed_lexicon,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return True, f"SUCCESS: Emitted {len(parsed_lexicon)} structured lexical entries.", len(parsed_lexicon)

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "tools/gha_factory/source_snapshots/kaikki_de_seed.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "build/lexical_output/lexicon_de.json"
    ok, msg, count = run_lexical_worker(src, dst)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    sys.exit(0 if ok else 1)
