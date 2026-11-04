"""Fail-closed, offline Route 05 handoff for original Wikidata Lexeme JSON.

This is a source-format adapter, NOT a source approval or production publisher.
Only an independently approved, exact-SHA256 Route 05 ledger entry can enqueue.
No glosses, translations, examples, audio, or CEFR are inferred or copied.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

MAX_LEXEME_BYTES = 4 * 1024 * 1024
QID = re.compile(r"Q[1-9][0-9]*\Z")
LEXEME = re.compile(r"L[1-9][0-9]*\Z")
SENSE = re.compile(r"L[1-9][0-9]*-S[1-9][0-9]*\Z")
FORM = re.compile(r"L[1-9][0-9]*-F[1-9][0-9]*\Z")
# Known Wikidata language items. Other registered languages can use a
# separately reviewed 'wikidata_language_qid' in their Route 05 source record.
LANGUAGE_QIDS = {"de": "Q188", "en": "Q1860", "ar": "Q13955",
                 "es": "Q1321", "fr": "Q150"}


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _qid_claims(sense, prop):
    claims = sense.get("claims", {})
    if not isinstance(claims, dict) or not isinstance(claims.get(prop, []), list):
        raise ValueError("invalid sense claims")
    ranked = claims.get(prop, [])
    if any(not isinstance(c, dict) for c in ranked):
        raise ValueError("invalid sense claim")
    ranked = [c for c in ranked if c.get("rank") != "deprecated"]
    if any(c.get("rank") == "preferred" for c in ranked):
        ranked = [c for c in ranked if c.get("rank") == "preferred"]
    values = []
    for claim in ranked:
        snak = claim.get("mainsnak", {})
        if not isinstance(snak, dict):
            raise ValueError("invalid source snak")
        if snak.get("snaktype") != "value":
            continue
        value = snak.get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item":
            qid = value.get("id")
            if isinstance(qid, str) and QID.fullmatch(qid) and qid not in values:
                values.append(qid)
    return values


def parse_lexeme(raw, language, source, script):
    """Extract only source-attested identity/forms/sense item claims."""
    from tools.gha_factory.admission.pipeline import AdmissionError, script_valid
    try:
        if len(raw) > MAX_LEXEME_BYTES:
            raise ValueError("oversized Lexeme JSON")
        doc = strict_json(raw)
        identity = source["retrieval"]["identity"]
        match = re.fullmatch(r"wikidata:Lexeme:(L[1-9][0-9]*):revision:([1-9][0-9]*)", identity)
        if not match or not isinstance(doc, dict) or set(doc) != {"entities"}:
            raise ValueError("source identity or entity envelope")
        lexeme_id, revision = match.groups()
        entities = doc["entities"]
        if not isinstance(entities, dict) or set(entities) != {lexeme_id}:
            raise ValueError("wrong or multiple Lexeme entities")
        entity = entities[lexeme_id]
        expected_qid = LANGUAGE_QIDS.get(language) or source.get("wikidata_language_qid")
        if (not isinstance(entity, dict) or entity.get("id") != lexeme_id
                or entity.get("lastrevid") != int(revision)
                or not isinstance(expected_qid, str) or not QID.fullmatch(expected_qid)
                or entity.get("language") != expected_qid
                or not isinstance(entity.get("lexicalCategory"), str)
                or not QID.fullmatch(entity["lexicalCategory"])):
            raise ValueError("Lexeme revision/language/category mismatch")
        lemmas = entity.get("lemmas", {})
        lemma = lemmas[language]["value"]
        if (not isinstance(lemma, str) or not lemma.strip() or len(lemma) > 256
                or not script_valid(lemma, script)):
            raise ValueError("unverified lemma script")
        forms, form_ids = [], set()
        for form in entity.get("forms", []):
            fid = form["id"]
            surface = form["representations"][language]["value"]
            features = form.get("grammaticalFeatures", [])
            if (not isinstance(fid, str) or not FORM.fullmatch(fid)
                    or not fid.startswith(lexeme_id + "-") or fid in form_ids
                    or not isinstance(surface, str) or not surface.strip()
                    or len(surface) > 256 or not script_valid(surface, script)
                    or not isinstance(features, list)
                    or any(not isinstance(q, str) or not QID.fullmatch(q) for q in features)):
                raise ValueError("unverified source form")
            form_ids.add(fid)
            forms.append({"form_id": fid, "surface": surface,
                          "grammatical_feature_qids": features})
        senses = entity.get("senses", [])
        if not isinstance(senses, list) or not senses:
            raise ValueError("no attested senses")
        rows, seen = [], set()
        for sense in senses:
            sid = sense["id"]
            if (not isinstance(sid, str) or not SENSE.fullmatch(sid)
                    or not sid.startswith(lexeme_id + "-") or sid in seen):
                raise ValueError("invalid or duplicate sense")
            seen.add(sid)
            content = {
                "lexeme_id": lexeme_id, "sense_id": sid, "lemma": lemma,
                "lexical_category_qid": entity["lexicalCategory"],
                "forms": forms,
                "concept_links": {prop: _qid_claims(sense, prop)
                                  for prop in ("P5137", "P9970")},
                "topic": "UNASSIGNED", "level": "UNKNOWN",
                "directed_translations": [], "examples": [],
                "review_status": "REVIEW_REQUIRED",
            }
            rows.append((sid, digest(canonical(sense)), content))
        return rows
    except (KeyError, IndexError, TypeError, UnicodeError, ValueError, AttributeError) as exc:
        raise AdmissionError("REJECTED_RECORD: invalid revision-pinned Lexeme source") from exc


def admit_lexeme(*, repo_root, source_id, input_path, out_dir, language,
                 dataset_version, part_size, script):
    from tools.gha_factory.admission.pipeline import AdmissionError, route05_source
    repo_root = Path(repo_root).resolve()
    input_path = Path(input_path)
    out_dir = Path(out_dir).absolute()
    # Approval is checked BEFORE parsing or writing anything.
    source = route05_source(repo_root, source_id, dataset_version,
                            input_path, "wikidata-lexeme-json")
    if out_dir.exists() or out_dir.is_symlink():
        raise AdmissionError("BLOCKED_SOURCE: output already exists")
    if not out_dir.parent.is_dir():
        raise AdmissionError("BLOCKED_SOURCE: output parent missing")
    with input_path.open("rb") as stream:
        raw = stream.read(MAX_LEXEME_BYTES + 1)
    rows = parse_lexeme(raw, language, source, script)
    license_info, retrieval = source["license"], source["retrieval"]
    jobs, stage = [], Path(tempfile.mkdtemp(prefix=".admission-", dir=out_dir.parent))
    try:
        for offset in range(0, len(rows), part_size):
            subset = rows[offset:offset + part_size]
            name = "partition-%08d.jsonl" % len(jobs)
            h = hashlib.sha256()
            with (stage / name).open("wb") as output:
                for sid, record_sha, content in subset:
                    row = {
                        "source_id": source_id, "dataset_version": dataset_version,
                        "language": language, "source_format": "wikidata-lexeme-json",
                        "license_id": "CC0-1.0",
                        "source_artifact_sha256": retrieval["sha256"],
                        "license_evidence_sha256": license_info["evidence_sha256"],
                        "source_record_id": sid, "source_record_sha256": record_sha,
                        "excluded_categories": ["source_glosses", "media", "examples"],
                        "content": content,
                    }
                    encoded = canonical(row)
                    output.write(encoded)
                    h.update(encoded)
                output.flush()
                os.fsync(output.fileno())
            job = {
                "source_id": source_id, "dataset_version": dataset_version,
                "language": language, "category": "lexeme_sense_candidate",
                "path": name, "sha256": h.hexdigest(),
                "record_count": len(subset), "partition_index": len(jobs),
                "license_id": "CC0-1.0",
                "license_evidence_sha256": license_info["evidence_sha256"],
            }
            job["resume_id"] = "srcadm1-" + digest(canonical([retrieval["sha256"], job]))[:40]
            jobs.append(job)
        report = {
            "schema_version": "1.0.0", "status": "ACCEPTED_FOR_QUEUE",
            "source_id": source_id, "dataset_version": dataset_version,
            "language": language, "source_format": "wikidata-lexeme-json",
            "source_artifact_sha256": retrieval["sha256"],
            "license_evidence_sha256": license_info["evidence_sha256"],
            "route05_reviewer_decision_url": source["review"]["decision_url"],
            "actual_accepted_records": len(rows), "jobs": jobs,
            "publication_approved": False, "production_ready": False,
            "note": "Source-approved review candidates only; separate QA and release gates required.",
        }
        (stage / "queue.json").write_bytes(canonical(report))
        if out_dir.exists() or out_dir.is_symlink():
            raise AdmissionError("BLOCKED_SOURCE: output concurrently created")
        stage.rename(out_dir)
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)
