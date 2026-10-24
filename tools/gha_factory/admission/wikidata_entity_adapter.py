"""Bounded, evidence-bound Wikidata Special:EntityData Lexeme adapter.

Only invoked AFTER Route 05 checks the exact approved artifact, license evidence,
reviewer, version and SHA256. Never grants rights or publishes a pack.
"""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MAX_ENTITY_BYTES = 1024 * 1024
_VERSION = re.compile(r"l([1-9][0-9]*)-r([1-9][0-9]*)\Z")
_QID = re.compile(r"Q[1-9][0-9]*\Z")


def extract_entity(raw, *, language, source, repo_root):
    from .pipeline import AdmissionError
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_ENTITY_BYTES:
        raise AdmissionError("REJECTED_RECORD: missing/oversized Wikidata entity")
    match = _VERSION.fullmatch(source.get("dataset_version", ""))
    if not match:
        raise AdmissionError("REJECTED_RECORD: invalid immutable Lexeme revision")
    lexeme_id, revision = "L" + match[1], int(match[2])
    url = urlsplit(source.get("origin_url", ""))
    if (url.scheme != "https" or url.netloc != "www.wikidata.org" or
            url.path != "/wiki/Special:EntityData/" + lexeme_id + ".json" or
            parse_qs(url.query) != {"revision": [str(revision)]} or url.fragment or
            source.get("retrieval", {}).get("identity") !=
            f"wikidata:Lexeme:{lexeme_id}:revision:{revision}"):
        raise AdmissionError("REJECTED_RECORD: source URL/revision identity mismatch")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise AdmissionError("REJECTED_RECORD: duplicate JSON property")
            obj[key] = value
        return obj
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise AdmissionError("REJECTED_RECORD: invalid Wikidata JSON") from exc
    entities = document.get("entities") if isinstance(document, dict) else None
    if not isinstance(entities, dict) or list(entities) != [lexeme_id]:
        raise AdmissionError("REJECTED_RECORD: wrong Wikidata Lexeme identity")
    entity = entities[lexeme_id]
    if (not isinstance(entity, dict) or entity.get("type") != "lexeme" or
            entity.get("id") != lexeme_id or type(entity.get("lastrevid")) is not int or
            entity["lastrevid"] != revision):
        raise AdmissionError("REJECTED_RECORD: unpinned Lexeme revision")
    root = Path(repo_root)
    try:
        registry = json.loads((root / "catalog/production_languages.v1.json").read_text(encoding="utf-8"))
        languages = {r["id"]: r["wikidata"] for r in registry["languages"]}
        sections = json.loads((root / "catalog/sections.v1.json").read_text(encoding="utf-8"))
        pos = sections["pos"].get(entity.get("lexicalCategory"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AdmissionError("REJECTED_RECORD: missing canonical language/POS evidence") from exc
    if entity.get("language") != languages.get(language) or not pos:
        raise AdmissionError("REJECTED_RECORD: language or POS is not attested in registry")
    lemmas = entity.get("lemmas")
    lemma = lemmas.get(language) if isinstance(lemmas, dict) else None
    word = lemma.get("value") if isinstance(lemma, dict) else None
    if not isinstance(word, str) or not word.strip() or len(word) > 256:
        raise AdmissionError("REJECTED_RECORD: missing attested lemma")
    senses, forms, seen = [], [], set()
    for s in entity.get("senses") or []:
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not re.fullmatch(re.escape(lexeme_id) + r"-S[1-9][0-9]*", sid) or sid in seen:
            raise AdmissionError("REJECTED_RECORD: invalid/duplicate sense identity")
        seen.add(sid)
        glosses = s.get("glosses")
        if not isinstance(glosses, dict) or not glosses:
            raise AdmissionError("REJECTED_RECORD: missing attested sense glosses")
        attested = {}
        for lang, value in glosses.items():
            gloss = value.get("value") if isinstance(value, dict) else None
            if not isinstance(lang, str) or not lang or not isinstance(gloss, str) or not gloss.strip() or len(gloss) > 10000:
                raise AdmissionError("REJECTED_RECORD: invalid attested gloss")
            attested[lang] = gloss
        senses.append({"sense_id": sid, "attested_glosses": attested})
    if not senses:
        raise AdmissionError("REJECTED_RECORD: Lexeme has no attested senses")
    for f in entity.get("forms") or []:
        fid = f.get("id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or not re.fullmatch(re.escape(lexeme_id) + r"-F[1-9][0-9]*", fid) or fid in seen:
            raise AdmissionError("REJECTED_RECORD: invalid/duplicate form identity")
        seen.add(fid)
        representations = f.get("representations")
        value = representations.get(language) if isinstance(representations, dict) else None
        surface = value.get("value") if isinstance(value, dict) else None
        features = f.get("grammaticalFeatures")
        if (not isinstance(surface, str) or not surface.strip() or
                not isinstance(features, list) or
                any(not isinstance(q, str) or not _QID.fullmatch(q) for q in features)):
            raise AdmissionError("REJECTED_RECORD: invalid attested form")
        forms.append({"form_id": fid, "surface": surface, "grammatical_feature_qids": features})
    # Glosses are source-language attestations, not directed translations.
    # Unreviewed claims/media are excluded rather than reinterpreted.
    return ({
        "word": word, "pos": pos, "lexeme_id": lexeme_id, "revision": revision,
        "senses": senses, "forms": forms, "directed_translations": [],
        "examples": [], "level": "UNKNOWN", "topic": "UNASSIGNED",
    }, ["unreviewed_claims", "media", "examples", "directed_translations"])
