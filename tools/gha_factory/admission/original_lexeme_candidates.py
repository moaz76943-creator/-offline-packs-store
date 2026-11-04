"""Deterministic REVIEW_REQUIRED sense candidates from revision-pinned CC0 Lexeme JSON.

No source approval, semantic translation, CEFR grade, example, or pack publication.
The original source bytes are already retained in legal/ledger/evidence/wikidata-20261023.
"""
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = Path("legal/ledger/evidence/wikidata-20261025-sense-candidates")
QID = re.compile(r"Q[1-9][0-9]*\Z")
LEXEME = re.compile(r"L[1-9][0-9]*\Z")
SENSE = re.compile(r"L[1-9][0-9]*-S[1-9][0-9]*\Z")
FORM = re.compile(r"L[1-9][0-9]*-F[1-9][0-9]*\Z")
SOURCE_LANGUAGE_QIDS = {"de": "Q188", "en": "Q1860", "ar": "Q13955"}
LICENSE_NOTICE_PATH = "legal/ledger/evidence/wikidata-20261023/copyright-1523614187.txt"
LICENSE_NOTICE_SHA256 = "a74df271d6e2cceb81f71967fb180c66d08c33a670d14d8b64448ee9ef286396"
# Independently recorded in main/legal/ledger/evidence/wikidata-20261023/review-receipt.json.
# A receipt may not authorize altered source bytes merely by changing its own SHA256.
SOURCE_SHA256 = {
    "L1026": "ce04495fa86963798a2bf5b0bbf65880d90268e74d3eed060de944f5f2c5cbb2",
    "L3006": "7e3bc9a51337eae5996b382c3ca3083266530ae15e2806a19b13ed9a076372fa",
    "L7882": "b147755e4266a4305d6dc2a0670d03025f1b938a4afa87e738ff8a73c370da5d",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON exponent")
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))


def pinned(root, path, expected):
    root = Path(root).resolve()
    if not isinstance(path, str) or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("missing source hash or path")
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in path:
        raise ValueError("unsafe source path")
    target = root
    for component in relative.parts:
        target = target / component
        if target.is_symlink():
            raise ValueError("symlink source")
    target = target.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("missing source")
    data = target.read_bytes()
    if digest(data) != expected:
        raise ValueError("source SHA256 mismatch")
    return data


def claim_qids(sense, property_id):
    claims = sense.get("claims", {}).get(property_id, [])
    if not isinstance(claims, list):
        raise ValueError("malformed source claims")
    claims = [c for c in claims if isinstance(c, dict) and c.get("rank") != "deprecated"]
    if any(c.get("rank") == "preferred" for c in claims):
        claims = [c for c in claims if c.get("rank") == "preferred"]
    values = []
    for claim in claims:
        snak = claim.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        value = snak.get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item":
            qid = value.get("id")
            if isinstance(qid, str) and QID.fullmatch(qid) and qid not in values:
                values.append(qid)
    return values


def build(root, receipt):
    if (receipt.get("schema_version") != 1 or receipt.get("status") != "REVIEW_REQUIRED"
            or receipt.get("license_id") != "CC0-1.0"
            or receipt.get("production_ready") is not False
            or receipt.get("source_admission_approved") is not False
            or receipt.get("original_lexeme_json_pinned") is not True):
        raise ValueError("review-only source gate")
    if receipt.get("license_evidence_path") != LICENSE_NOTICE_PATH:
        raise ValueError("untrusted license evidence path")
    if receipt.get("license_evidence_sha256") != LICENSE_NOTICE_SHA256:
        raise ValueError("license notice hash not independently pinned")
    notice = pinned(root, receipt["license_evidence_path"], LICENSE_NOTICE_SHA256)
    if b"Lexeme" not in notice or b"Creative Commons CC0 License" not in notice:
        raise ValueError("scoped Wikidata license evidence missing")
    lexemes, candidates, identities = [], [], set()
    source_identities = set()
    for source in receipt["source_files"]:
        language, lexeme_id = source["language"], source["lexeme_id"]
        if (language, lexeme_id) in source_identities:
            raise ValueError("duplicate source lexeme")
        source_identities.add((language, lexeme_id))
        if source.get("language_qid") != SOURCE_LANGUAGE_QIDS.get(language):
            raise ValueError("untrusted source language QID")
        if (language not in ("de", "en", "ar") or not LEXEME.fullmatch(lexeme_id)
                or source["path"] != "legal/ledger/evidence/wikidata-20261023/%s-%s.json" %
                (lexeme_id, source["revision"])):
            raise ValueError("untrusted original source")
        if source.get("sha256") != SOURCE_SHA256.get(lexeme_id):
            raise ValueError("source hash not independently pinned")
        raw = pinned(root, source["path"], SOURCE_SHA256[lexeme_id])
        entity = strict_json(raw)["entities"][lexeme_id]
        if (entity.get("id") != lexeme_id or entity.get("lastrevid") != source["revision"]
                or entity.get("language") != source["language_qid"]
                or entity.get("lexicalCategory") != "Q24905"
                or len(entity.get("forms", [])) != source["forms"]
                or len(entity.get("senses", [])) != source["senses"]):
            raise ValueError("original lexeme identity/revision mismatch")
        lemma = entity["lemmas"][language]["value"]
        if not isinstance(lemma, str) or not lemma.strip():
            raise ValueError("missing source lemma")
        forms, form_ids = [], set()
        for form in entity["forms"]:
            form_id = form["id"]
            surface = form["representations"][language]["value"]
            features = form.get("grammaticalFeatures", [])
            if (not FORM.fullmatch(form_id) or not form_id.startswith(lexeme_id + "-")
                    or form_id in form_ids or not isinstance(surface, str) or not surface.strip()
                    or not isinstance(features, list) or any(not isinstance(q, str) or not QID.fullmatch(q) for q in features)):
                raise ValueError("invalid attested form")
            form_ids.add(form_id)
            forms.append({"form_id": form_id, "surface": surface, "grammatical_feature_qids": features})
        lexemes.append({"language": language, "lexeme_id": lexeme_id, "lemma": lemma,
                        "lexical_category_qid": entity["lexicalCategory"], "forms": forms,
                        "revision": source["revision"], "source_snapshot": source["path"],
                        "source_sha256": source["sha256"]})
        for sense in entity["senses"]:
            sense_id = sense["id"]
            if not SENSE.fullmatch(sense_id) or not sense_id.startswith(lexeme_id + "-"):
                raise ValueError("invalid attested sense")
            identity = (language, lexeme_id, sense_id)
            if identity in identities:
                raise ValueError("duplicate sense")
            identities.add(identity)
            links = {"P5137": claim_qids(sense, "P5137"), "P9970": claim_qids(sense, "P9970")}
            mapped = "Q19279529" in links["P9970"]
            candidates.append({
                "id": ":".join(identity), "language": language, "lexeme_id": lexeme_id,
                "sense_id": sense_id, "concept_links": links,
                "topic": "activities" if mapped else "UNASSIGNED",
                "topic_status": "MAPPED_ESTIMATE" if mapped else "UNKNOWN",
                "subtopic": None, "scenario": None, "intent": None, "skill": None,
                "grammar": None, "level": "UNKNOWN", "level_evidence": None,
                "directed_translations": [], "examples": [],
                "source_id": "wikidata.lexemes", "source_snapshot": source["path"],
                "review_status": "REVIEW_REQUIRED"})
    lexemes.sort(key=lambda x: x["language"])
    candidates.sort(key=lambda x: x["id"])
    if (len(candidates) != receipt["actual_rows"] or len(lexemes) != receipt["lexeme_count"]
            or sum(len(l["forms"]) for l in lexemes) != receipt["form_count"]
            or sum(c["topic"] == "activities" for c in candidates) != receipt["topic_estimates"]
            or sum(c["topic"] == "UNASSIGNED" for c in candidates) != receipt["unassigned_topics"]):
        raise ValueError("source-derived count mismatch")
    return {"schema_version": 1, "actual_rows": len(candidates),
            "lexeme_count": len(lexemes), "form_count": sum(len(l["forms"]) for l in lexemes),
            "candidates": candidates, "lexemes": lexemes,
            "review_status": "REVIEW_REQUIRED", "production_ready": False,
            "source_admission_approved": False}


if __name__ == "__main__":
    receipt = strict_json((ROOT / FOLDER / "receipt.json").read_bytes())
    candidate = (ROOT / FOLDER / "candidates.json").read_bytes()
    if canonical(build(ROOT, receipt)) != candidate or digest(candidate) != receipt["candidate_sha256"]:
        raise SystemExit("FAIL: original Lexeme candidate reconstruction differs")
    print("PASS: original source-attested review-only senses =", receipt["actual_rows"])
