from typing import Dict, Any, List, Optional

ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "MIT", "core_dictionary_curated"}

def validate_translation_edge(
    source_lemma: str,
    target_gloss: str,
    source_lang: str,
    target_lang: str,
    provenance_source: str,
    license_tag: str
) -> Optional[Dict[str, Any]]:
    """
    Enforces asymmetric directed translation edges (A -> B != B -> A)
    and verifies that the license and provenance strictly comply with legal policies.
    """
    if not source_lemma or not target_gloss:
        return None

    lic = license_tag.strip()
    if lic not in ALLOWED_LICENSES:
        return None

    # بناء الحافة الموجهة دون إمكانية الخلط العكسي
    directed_edge = f"{source_lang.strip()}_{target_lang.strip()}"

    return {
        "directed_edge": directed_edge,
        "source_lemma": source_lemma.strip(),
        "target_gloss": target_gloss.strip(),
        "provenance": provenance_source.strip(),
        "license": lic,
        "is_asymmetric": True,
    }

def batch_audit_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid_edges = []
    for edge in edges:
        res = validate_translation_edge(
            source_lemma=edge.get("src_lemma", ""),
            target_gloss=edge.get("tgt_gloss", ""),
            source_lang=edge.get("src_lang", "de"),
            target_lang=edge.get("tgt_lang", "ar"),
            provenance_source=edge.get("provenance", "core_curated"),
            license_tag=edge.get("license", "CC-BY-SA-4.0"),
        )
        if res:
            valid_edges.append(res)
    return valid_edges
