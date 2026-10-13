"""Sparse, fail-closed directed lexical-sense graph. Stdlib only; no corpus downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_LINE = 65536
MAX_CANDIDATES = 100000
MAX_DOCUMENT = 16 * 1024 * 1024

class AdmissionError(ValueError):
    """External evidence is missing, conflicting, or not independently admissible."""

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(65536), b""):
            h.update(data)
    return h.hexdigest()

def pinned(path, expected=None):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise AdmissionError("UNSAFE_OR_MISSING_INPUT")
    actual = digest(path)
    if expected is not None and (not SHA.fullmatch(expected) or actual != expected):
        raise AdmissionError("STALE_OR_INVALID_SNAPSHOT")
    return actual

def json_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise AdmissionError("DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj

def document(path, expected=None):
    pinned(path, expected)
    if Path(path).stat().st_size > MAX_DOCUMENT:
        raise AdmissionError("OVERSIZED_DOCUMENT")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=json_object)

def registry_ids(path):
    data = document(path)
    ids = [x["id"] for x in data["languages"]]
    if len(ids) != 100 or len(set(ids)) != 100:
        raise AdmissionError("CANONICAL_100_IDS_REQUIRED")
    return ids

def approved(source, ledger):
    """An input's own approval flag never replaces the independent Route-05 ledger."""
    if not isinstance(source, dict):
        return False
    record = ledger.get(source.get("source_id"))
    if not isinstance(record, dict) or record.get("status") != "APPROVED_FOR_REDISTRIBUTION":
        return False
    license_record = record.get("license") or {}
    retrieval = record.get("retrieval") or {}
    if not record.get("review") or not license_record.get("id") or not SHA.fullmatch(str(retrieval.get("sha256", ""))):
        return False
    if source.get("publication_approved") is not True or source.get("fixture_only") is not False:
        return False
    for key, val in (
        ("source_id", record.get("source_id")),
        ("dataset_version", record.get("dataset_version")),
        ("license_id", license_record.get("id")),
        ("publisher", record.get("publisher")),
        ("origin_url", record.get("origin_url")),
        ("artifact_sha256", retrieval.get("sha256")),
    ):
        if not isinstance(val, str) or not val or source.get(key) != val:
            return False
    return all(isinstance(source.get(key), str) and source[key].strip()
               for key in ("record_locator", "retrieval_id"))

def ledger_index(path):
    obj = document(path)
    if obj.get("schema_version") != "1.0.0" or not isinstance(obj.get("sources"), list):
        raise AdmissionError("INVALID_RIGHTS_LEDGER")
    out = {}
    for source in obj["sources"]:
        sid = source.get("source_id")
        if not isinstance(sid, str) or sid in out:
            raise AdmissionError("DUPLICATE_LEDGER_SOURCE")
        out[sid] = source
    return out

def connect(path):
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS senses (
            sense_id TEXT PRIMARY KEY, language TEXT NOT NULL, lexeme_id TEXT NOT NULL,
            concept_id TEXT NOT NULL, script TEXT NOT NULL, lemma TEXT NOT NULL,
            surface TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS edges (
            translation_id TEXT PRIMARY KEY, source_language TEXT NOT NULL,
            target_language TEXT NOT NULL, from_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
            to_sense_id TEXT NOT NULL REFERENCES senses(sense_id), status TEXT NOT NULL
            CHECK(status IN ('verified','review_required')),
            equivalence TEXT NOT NULL, translation_text TEXT NOT NULL, context TEXT,
            domain TEXT, register TEXT, dialect TEXT, source_id TEXT NOT NULL,
            dataset_version TEXT NOT NULL, license_id TEXT NOT NULL,
            locator TEXT NOT NULL, source_sha256 TEXT NOT NULL,
            FOREIGN KEY(to_sense_id) REFERENCES senses(sense_id));
        CREATE INDEX IF NOT EXISTS edge_pair ON edges(source_language,target_language,status);
    """)
    return db

def load_senses(db, lexical, ids, ledger):
    if not lexical:
        return 0
    if lexical.get("contract_version") != "1.0.0":
        raise AdmissionError("UNRECOGNIZED_LEXICAL_CONTRACT")
    lexemes = {}
    for item in lexical.get("lexemes", []):
        lid = item["lexeme_id"]
        if lid in lexemes:
            raise AdmissionError("DUPLICATE_LEXEME")
        if item["language"] not in ids:
            raise AdmissionError("NONCANONICAL_LEXEME_LANGUAGE")
        lexemes[lid] = item
    seen = set()
    admitted = 0
    for sense in lexical.get("senses", []):
        sid = sense["sense_id"]
        if sid in seen:
            raise AdmissionError("DUPLICATE_SENSE")
        seen.add(sid)
        lex = lexemes.get(sense.get("lexeme_id"))
        if lex is None:
            raise AdmissionError("ORPHAN_CANONICAL_SENSE")
        if not approved(sense.get("source"), ledger) or not approved(lex.get("source"), ledger):
            continue
        db.execute("""INSERT INTO senses VALUES (?,?,?,?,?,?,?)
                  ON CONFLICT(sense_id) DO NOTHING""",
                  (sid, lex["language"], lex["lexeme_id"], sense["concept_id"],
                   lex["script"], lex["lemma"], lex["surface"]))
        prior = db.execute("SELECT language,lexeme_id,concept_id,script,lemma,surface FROM senses WHERE sense_id=?",
                           (sid,)).fetchone()
        if prior != (lex["language"], lex["lexeme_id"], sense["concept_id"],
                     lex["script"], lex["lemma"], lex["surface"]):
            raise AdmissionError("STABLE_SENSE_ID_REASSIGNED")
        admitted += 1
    db.commit()
    return admitted

def each_candidate(path, source_sha):
    pinned(path, source_sha)
    count = 0
    with Path(path).open("rb") as stream:
        first = stream.read(1)
        stream.seek(0)
        if first == b"{" and Path(path).stat().st_size <= MAX_DOCUMENT:
            # A PR #79 document is one JSON object. Multiple JSONL records must
            # NOT be parsed as one document. Never overwrite direction labels.
            raw = stream.read()
            try:
                data = json.loads(raw.decode("utf-8"), object_pairs_hook=json_object)
            except json.JSONDecodeError as exc:
                if "Extra data" not in str(exc):
                    raise
                data = None
            if isinstance(data, dict) and "translations" in data:
                if data.get("contract_version") != "1.0.0":
                    raise AdmissionError("BAD_DIRECTED_PAIR_CONTRACT")
                for entry in data["translations"]:
                    rec = dict(entry)
                    rec.setdefault("source_language", data["source_language"])
                    rec.setdefault("target_language", data["target_language"])
                    yield rec
                return
            stream.seek(0)
        for raw in stream:
            count += 1
            if count > MAX_CANDIDATES or len(raw) > MAX_LINE:
                raise AdmissionError("CANDIDATE_SHARD_BUDGET_EXCEEDED")
            if raw.strip():
                yield json.loads(raw.decode("utf-8"), object_pairs_hook=json_object)

def reviews_index(path, sha, candidate_sha):
    if not path:
        return {}
    data = document(path, sha)
    if data.get("schema_version") != "1.0.0" or data.get("candidate_sha256") != candidate_sha:
        raise AdmissionError("REVIEW_NOT_BOUND_TO_CANDIDATE_SNAPSHOT")
    out = {}
    for review in data.get("reviews", []):
        rid = review.get("translation_id")
        if not isinstance(rid, str) or rid in out:
            raise AdmissionError("DUPLICATE_REVIEW")
        out[rid] = review
    return out

def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2000

def admit(db, item, ids, ledger, reviews, candidate_sha):
    tid = item.get("translation_id")
    if not _text(tid) or len(tid) > 128:
        raise AdmissionError("INVALID_EDGE_ID")
    a = db.execute("SELECT language,concept_id,script,lemma,surface FROM senses WHERE sense_id=?",
                   (item.get("from_sense_id"),)).fetchone()
    b = db.execute("SELECT language,concept_id,script,lemma,surface FROM senses WHERE sense_id=?",
                   (item.get("to_sense_id"),)).fetchone()
    if not a or not b:
        raise AdmissionError("UNVERIFIED_OR_MISSING_SENSE")
    source_lang, target_lang = a[0], b[0]
    if source_lang not in ids or target_lang not in ids or source_lang == target_lang:
        raise AdmissionError("INVALID_DIRECTION")
    if item.get("source_language", source_lang) != source_lang or item.get("target_language", target_lang) != target_lang:
        raise AdmissionError("LANGUAGE_IDENTITY_SWAP")
    if item.get("from_script", a[2]) != a[2] or item.get("to_script", b[2]) != b[2]:
        raise AdmissionError("SCRIPT_IDENTITY_SWAP")
    if not _text(item.get("translation_text", item.get("text"))):
        raise AdmissionError("MISSING_TRANSLATION_TEXT")
    text = item.get("translation_text", item.get("text"))
    if text not in (b[3], b[4]):
        raise AdmissionError("TARGET_LEXEME_TEXT_MISMATCH")
    if item.get("language", target_lang) != target_lang:
        raise AdmissionError("TARGET_LANGUAGE_MISMATCH")
    equivalence = item.get("equivalence")
    if equivalence not in ("exact", "approximate", "contextual", "literal", "cultural"):
        raise AdmissionError("INVALID_EQUIVALENCE")
    if equivalence == "exact" and a[1] != b[1]:
        raise AdmissionError("WRONG_SENSE_CONCEPT")
    if equivalence != "exact" and not _text(item.get("context")):
        raise AdmissionError("CONTEXT_REQUIRED")
    source = item.get("source")
    if not approved(source, ledger):
        raise AdmissionError("SOURCE_RIGHTS_OR_PROVENANCE_BLOCKED")
    evidence = item.get("evidence") or {}
    if (evidence.get("kind") != "direct_sense_attestation"
            or evidence.get("from_sense_id") != item["from_sense_id"]
            or evidence.get("to_sense_id") != item["to_sense_id"]
            or evidence.get("source_sha256") != source["artifact_sha256"]
            or not _text(evidence.get("record_locator"))):
        raise AdmissionError("DIRECT_SENSE_EVIDENCE_MISSING")
    review = reviews.get(tid, {})
    matched = (review.get("decision") == "approved"
               and review.get("from_sense_id") == item["from_sense_id"]
               and review.get("to_sense_id") == item["to_sense_id"]
               and review.get("source_language") == source_lang
               and review.get("target_language") == target_lang
               and review.get("source_sha256") == source["artifact_sha256"]
               and review.get("candidate_sha256") == candidate_sha
               and _text(review.get("reviewer")) and _text(review.get("review_id"))
               and _text(review.get("evidence_locator")))
    status = "verified" if matched else "review_required"
    before = db.execute("SELECT * FROM edges WHERE translation_id=?", (tid,)).fetchone()
    record = (tid, source_lang, target_lang, item["from_sense_id"], item["to_sense_id"],
              status, equivalence, text, item.get("context"), item.get("domain"),
              item.get("register"), item.get("dialect"), source["source_id"],
              source["dataset_version"], source["license_id"],
              source["record_locator"], source["artifact_sha256"])
    if before is not None:
        if before != record:
            raise AdmissionError("EDGE_ID_REASSIGNED")
        raise AdmissionError("DUPLICATE_EDGE_ID")
    db.execute("INSERT INTO edges VALUES (" + ",".join("?" for _ in record) + ")", record)
    return status

def coverage(db, ids):
    rows = db.execute("""SELECT source_language,target_language,status,COUNT(*)
                         FROM edges GROUP BY source_language,target_language,status""").fetchall()
    counts = {(a, b, st): n for a, b, st, n in rows}
    matrix = []
    for a in ids:
        for b in ids:
            if a == b:
                continue
            v, r = counts.get((a,b,"verified"), 0), counts.get((a,b,"review_required"), 0)
            matrix.append({"source_language":a,"target_language":b,
                           "verified":v,"review_required":r,
                           "unavailable":v+r == 0,
                           "status":"verified" if v else ("review_required" if r else "unavailable")})
    return matrix

def write_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise AdmissionError("UNSAFE_OUTPUT")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial." + str(os.getpid()))
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":")) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def execute(*, registry, sources, lexical=None, lexical_sha=None, candidates=None,
            candidates_sha=None, reviews=None, reviews_sha=None, database=":memory:",
            interface_language="ar", shard_count=1, shard_index=0, receipt=None, matrix=None):
    ids = registry_ids(registry)
    if interface_language not in ids:
        raise AdmissionError("NONCANONICAL_INTERFACE_LANGUAGE")
    if shard_count not in (1,2,4,8,16) or not 0 <= shard_index < shard_count:
        raise AdmissionError("INVALID_SHARD")
    if candidates and not candidates_sha:
        raise AdmissionError("CANDIDATE_SHA_REQUIRED")
    if lexical and not lexical_sha:
        raise AdmissionError("LEXICAL_SHA_REQUIRED")
    if reviews and not reviews_sha:
        raise AdmissionError("REVIEW_SHA_REQUIRED")
    source_sha = pinned(sources)
    led = ledger_index(sources)
    db = connect(database)
    try:
        admitted_senses = load_senses(db, document(lexical, lexical_sha) if lexical else None, ids, led)
        candidate_sha = pinned(candidates, candidates_sha) if candidates else None
        reviews_map = reviews_index(reviews, reviews_sha, candidate_sha) if reviews else {}
        counts = {"verified":0,"review_required":0,"blocked":0,"shard_candidates":0}
        reasons = {}
        if candidates:
            for item in each_candidate(candidates, candidate_sha):
                if not isinstance(item, dict):
                    raise AdmissionError("INVALID_CANDIDATE_OBJECT")
                tid = item.get("translation_id")
                if not _text(tid):
                    raise AdmissionError("CANDIDATE_MISSING_ID")
                if int(hashlib.sha256(tid.encode("utf-8")).hexdigest(),16) % shard_count != shard_index:
                    continue
                counts["shard_candidates"] += 1
                try:
                    with db:
                        status = admit(db, item, ids, led, reviews_map, candidate_sha)
                    counts[status] += 1
                except AdmissionError as exc:
                    counts["blocked"] += 1
                    reasons[str(exc)] = reasons.get(str(exc), 0) + 1
        all_pairs = coverage(db, ids)
        report = {"schema_version":"1.0.0","registry_sha256":digest(registry),
                  "source_ledger_sha256":source_sha,"lexical_sha256":digest(lexical) if lexical else None,
                  "candidate_sha256":candidate_sha,"review_sha256":digest(reviews) if reviews else None,
                  "interface_language":interface_language,"canonical_languages":100,
                  "theoretical_directed_pairs":9900,"admitted_senses":admitted_senses,
                  "shard_count":shard_count,"shard_index":shard_index,
                  "counts":counts,"blocked_reasons":dict(sorted(reasons.items())),
                  "covered_pairs":sum(not x["unavailable"] for x in all_pairs),
                  "unavailable_pairs":sum(x["unavailable"] for x in all_pairs),
                  "run_id":os.environ.get("GITHUB_RUN_ID"),"run_attempt":os.environ.get("GITHUB_RUN_ATTEMPT"),
                  "commit_sha":os.environ.get("GITHUB_SHA")}
        if matrix:
            write_json(matrix, {"receipt":report,"pairs":all_pairs})
        if receipt:
            write_json(receipt, report)
        return report
    finally:
        db.close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry",default=str(ROOT/"catalog/language_registry.v1.json"))
    p.add_argument("--sources",default=str(ROOT/"legal/ledger/sources.json"))
    for name in ("lexical","candidates","reviews"):
        p.add_argument("--"+name)
        p.add_argument("--"+name+"-sha256")
    p.add_argument("--database",default=":memory:")
    p.add_argument("--interface-language",default="ar")
    p.add_argument("--shard-count",type=int,default=1)
    p.add_argument("--shard-index",type=int,default=0)
    p.add_argument("--receipt")
    p.add_argument("--matrix")
    args = vars(p.parse_args())
    for x in ("lexical","candidates","reviews"):
        args[x+"_sha"] = args.pop(x+"_sha256")
    print(json.dumps(execute(**args),sort_keys=True,ensure_ascii=False))

if __name__ == "__main__":
    main()
