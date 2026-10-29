from typing import Dict, Any, List, Optional

def align_directed_example(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    lemma: str,
    cefr_level: str = "A1"
) -> Optional[Dict[str, Any]]:
    """
    Enforces the Directed Pair Law: A -> B != B -> A.
    Filters invalid lengths and builds an immutable directed sentence alignment record.
    """
    src = source_text.strip()
    tgt = target_text.strip()

    if not src or not tgt or len(src) < 3 or len(tgt) < 3:
        return None

    # منع التناظر الخاطئ وحفظ اتجاه الحافة الموجهة
    directed_pair = f"{source_lang}_{target_lang}"

    return {
        "directed_pair": directed_pair,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_sentence": src,
        "target_sentence": tgt,
        "associated_lemma": lemma.strip(),
        "cefr_level": cefr_level.upper(),
    }

def batch_align_examples(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    aligned = []
    for p in pairs:
        res = align_directed_example(
            source_text=p.get("src", ""),
            target_text=p.get("tgt", ""),
            source_lang=p.get("src_lang", "de"),
            target_lang=p.get("tgt_lang", "ar"),
            lemma=p.get("lemma", ""),
            cefr_level=p.get("cefr", "A1")
        )
        if res:
            aligned.append(res)
    return aligned
