#!/usr/bin/env python3
"""
Language-Aware Unicode Normalization Engine - Master Constitution Section 07 Compliant.
Handles script-specific linguistics:
- Turkish/Azeri dotted/dotless I distinction
- Arabic diacritics (Tashkeel), Tatweel, and Hamza harmonization
- German Umlaut & Eszett NFC canonical representation
"""
import re
import unicodedata

# Arabic Tashkeel Unicode range: U+064B through U+065F, plus U+0670 (Superscript Alef)
ARABIC_DIACRITICS_REGEX = re.compile(r'[\u064B-\u065F\u0670]')
ARABIC_TATWEEL = '\u0640'

def normalize_turkish(text: str, to_lower: bool = True) -> str:
    """Preserves distinct Turkish dotted (i/İ) and dotless (ı/I) graphemes."""
    nfc_text = unicodedata.normalize('NFC', text)
    if not to_lower:
        return nfc_text
    # Turkish-specific lowercasing mapping
    # Capital 'I' (U+0049) -> small dotless 'ı' (U+0131)
    # Capital 'İ' (U+0130) -> small dotted 'i' (U+0069)
    result = []
    for ch in nfc_text:
        if ch == 'I':
            result.append('\u0131') # 'ı'
        elif ch == '\u0130':
            result.append('i')
        else:
            result.append(ch.lower())
    return "".join(result)

def normalize_arabic(text: str, strip_tashkeel: bool = False, harmonize_hamza: bool = False) -> str:
    """Normalizes Arabic text with optional Tashkeel stripping and Hamza harmonization for search."""
    nfc_text = unicodedata.normalize('NFC', text)
    # Remove Tatweel / Kashida
    cleaned = nfc_text.replace(ARABIC_TATWEEL, '')

    if strip_tashkeel:
        cleaned = ARABIC_DIACRITICS_REGEX.sub('', cleaned)

    if harmonize_hamza:
        # Harmonize Alef with Hamza variants to bare Alef: أ, إ, آ -> ا
        cleaned = re.sub(r'[\u0622\u0623\u0625]', '\u0627', cleaned)
        # Harmonize Taa Marbuta: ة -> ه
        cleaned = cleaned.replace('\u0629', '\u0647')
        # Harmonize Yaa variants: ى -> ي
        cleaned = cleaned.replace('\u0649', '\u064A')

    return cleaned.strip()

def normalize_for_language(text: str, lang_code: str, search_mode: bool = False) -> str:
    """Dispatches language-specific normalization pipeline based on ISO 639-1 code."""
    if not text:
        return ""
    code = lang_code.lower().split('_')[0]

    if code in ['tr', 'az']:
        return normalize_turkish(text, to_lower=search_mode)
    elif code == 'ar':
        return normalize_arabic(text, strip_tashkeel=search_mode, harmonize_hamza=search_mode)
    else:
        # Canonical standard NFC normalization
        normalized = unicodedata.normalize('NFC', text.strip())
        return normalized.lower() if search_mode else normalized

if __name__ == "__main__":
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else "إِنَّ اللَّهَ مَعَ الصَّابِرِينَ"
    lang = sys.argv[2] if len(sys.argv) > 2 else "ar"
    print(f"Original: {sample}")
    print(f"Canonical NFC: {normalize_for_language(sample, lang, search_mode=False)}")
    print(f"Search Key:    {normalize_for_language(sample, lang, search_mode=True)}")
