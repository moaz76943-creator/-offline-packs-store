import re

def normalize_arabic_hebrew(text, lang):
    """Normalize Arabic and Hebrew diacritics using approved rules."""
    if not text:
        return text
    if lang == 'ar':
        # Remove Arabic vowel marks (Tashkeel)
        text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
        # Normalize alef variants to bare alef
        text = re.sub(r'[\u0622\u0623\u0625]', '\u0627', text)
    elif lang == 'he':
        # Remove Hebrew Niqqud
        text = re.sub(r'[\u0591-\u05C7]', '', text)
    return text

def normalize_text(text, lang):
    return normalize_arabic_hebrew(text, lang)
