import re
import unicodedata

# رموز التشكيل العربية الشائعة
ARABIC_DIACRITICS_REGEX = re.compile(r'[\u064B-\u0652\u0670\u0640]')

def normalize_arabic(text: str) -> str:
    """تجريد التشكيل وتوحيد الألفات والياء والتاء المربوطة للبحث"""
    if not text:
        return ""
    # 1. إزالة التشكيل والتطويل
    t = ARABIC_DIACRITICS_REGEX.sub('', text)
    # 2. توحيد الهمزات والألف
    t = re.sub(r'[إأآا]', 'ا', t)
    # 3. توحيد الياء والتاء المربوطة
    t = re.sub(r'ة', 'ه', t)
    t = re.sub(r'ى', 'ي', t)
    return unicodedata.normalize("NFC", t.strip())

def fold_german_umlauts(text: str) -> str:
    """تحويل الأوملاوت لإنشاء مفاتيح بحث بديلة (ä -> ae, ö -> oe, ü -> ue, ß -> ss)"""
    if not text:
        return ""
    replacements = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue'
    }
    t = text
    for k, v in replacements.items():
        t = t.replace(k, v)
    return unicodedata.normalize("NFC", t)

def normalize_turkish_case(text: str, to_lower: bool = True) -> str:
    """معالجة النقطة الخاصة بحرف I في التركية (I -> ı و İ -> i)"""
    if not text:
        return ""
    if to_lower:
        return text.replace('İ', 'i').replace('I', 'ı').lower()
    return text.replace('i', 'İ').replace('ı', 'I').upper()
