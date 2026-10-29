#!/usr/bin/env python3
"""
Examples Worker - Master Constitution Section 02 & 08 Compliant.
Guarantees directed pair isolation (A->B != B->A), sense-level binding,
and NFC Unicode normalization on sentence pairs.
"""
import json
import os
import sys
import unicodedata

def clean_sentence(text: str) -> str:
    if not text:
        return ""
    # Normalize Unicode NFC and strip rogue whitespace/control chars
    normalized = unicodedata.normalize('NFC', text.strip())
    # Remove redundant inner whitespace
    return " ".join(normalized.split())

def validate_and_parse_example(pair: dict, source_lang: str, target_lang: str) -> dict:
    term = clean_sentence(pair.get('term', ''))
    src_text = clean_sentence(pair.get('source_text', ''))
    tgt_text = clean_sentence(pair.get('target_text', ''))
    sense_hint = clean_sentence(pair.get('sense_hint', 'default_sense'))

    # Sanity: must be a legitimate sentence, not an isolated single word
    if len(src_text.split()) < 2 or len(tgt_text.split()) < 2:
        return None

    if not term or not src_text or not tgt_text:
        return None

    return {
        'term': term,
        'sense_hint': sense_hint,
        'source_lang': source_lang,
        'target_lang': target_lang,
        'source_sentence': src_text,
        'target_sentence': tgt_text,
    }

def run_examples_worker(snapshot_path: str, output_path: str):
    if not os.path.exists(snapshot_path):
        return False, f"SNAPSHOT_NOT_FOUND: {snapshot_path}", 0

    with open(snapshot_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    src_lang = data.get('source_lang', 'de')
    tgt_lang = data.get('target_lang', 'ar')
    raw_pairs = data.get('sentence_pairs', [])

    valid_examples = []
    for item in raw_pairs:
        parsed = validate_and_parse_example(item, src_lang, tgt_lang)
        if parsed:
            valid_examples.append(parsed)

    if not valid_examples:
        return False, "ZERO_YIELD: No valid example sentence pairs parsed.", 0

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    payload = {
        'schema': 'polyglot_examples_v2',
        'pair': f"{src_lang}->{tgt_lang}",
        'count': len(valid_examples),
        'examples': valid_examples,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return True, f"SUCCESS: Generated {len(valid_examples)} aligned sentence examples.", len(valid_examples)

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "tools/gha_factory/source_snapshots/examples_de_ar_seed.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "build/examples_output/examples_de_ar.json"
    ok, msg, count = run_examples_worker(src, dst)
    print(f"[{'PASS' if ok else 'FAIL'}] {msg}")
    sys.exit(0 if ok else 1)
