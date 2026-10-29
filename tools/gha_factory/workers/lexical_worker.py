import unicodedata
from typing import Dict, Any, List, Optional

def normalize_text_nfc(text: str) -> str:
    """Enforces canonical Unicode NFC normalization across all lexical terms."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text.strip())

def parse_kaikki_entry(raw_entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parses a single Wiktionary/Kaikki JSON record into normalized multi-sense schema.
    Extracts lemma, pos, ipa, gender, and senses with deduplicated glosses.
    """
    word = raw_entry.get("word")
    pos = raw_entry.get("pos")
    if not word or not pos:
        return None

    norm_word = normalize_text_nfc(word)
    senses = raw_entry.get("senses", [])
    extracted_glosses = []

    for sense in senses:
        glosses = sense.get("glosses", [])
        for g in glosses:
            norm_g = normalize_text_nfc(g)
            if norm_g and norm_g not in extracted_glosses:
                extracted_glosses.append(norm_g)

    # استخراج الرموز الصوتية IPA إن وجدت
    ipa = None
    for sound in raw_entry.get("sounds", []):
        if "ipa" in sound:
            ipa = sound["ipa"]
            break

    return {
        "lemma": norm_word,
        "pos": pos.lower(),
        "ipa": ipa,
        "senses_count": len(extracted_glosses),
        "glosses": extracted_glosses,
    }
