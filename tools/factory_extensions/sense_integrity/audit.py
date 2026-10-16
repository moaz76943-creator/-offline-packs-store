"""Read-only, disk-indexed lexical sense integrity QA. No canonical writes or inferred edges."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path

KINDS = {"lexemes": "lexeme_id", "senses": "sense_id",
         "translations": "translation_id", "relations": "relation_id",
         "examples": "example_id"}
REQUIRED = {
    "lexemes": ("language", "script", "lemma", "surface", "pos", "direction"),
    "senses": ("lexeme_id", "concept_id", "definition"),
    "translations": ("from_sense_id", "to_sense_id", "language", "text"),
    "relations": ("from_lexeme_id", "to_lexeme_id", "kind"),
    "examples": ("sense_id", "language", "script", "text"),
}
MAX_JSONL_LINE = 2 * 1024 * 1024
DDL = """
CREATE TABLE rec(
 snapshot TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
 language TEXT, script TEXT, lemma TEXT, pos TEXT, dialect TEXT,
 register TEXT, homograph TEXT, parent TEXT, concept TEXT, definition TEXT,
 left_id TEXT, right_id TEXT, target_lang TEXT, pinned TEXT NOT NULL,
 source_ok INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(snapshot, kind, id));
CREATE INDEX lex_group ON rec(snapshot,kind,language,script,lemma,pos,dialect,register,homograph,id);
CREATE INDEX sense_owner ON rec(snapshot,kind,parent,concept,id);
CREATE TABLE issue(language TEXT NOT NULL, severity TEXT NOT NULL,
 code TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE review(candidate_id TEXT PRIMARY KEY, disposition TEXT NOT NULL,
 reviewer TEXT NOT NULL, reference TEXT NOT NULL);
"""
DISPOSITIONS = {"distinct", "merge_approved", "rejected", "needs_review"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def strict_json(s):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(s, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError("invalid numeric constant: " + value)))


def lines(path):
    with path.open("rb") as handle:
        number = 0
        while True:
            raw = handle.readline(MAX_JSONL_LINE + 1)
            if not raw:
                break
            number += 1
            if len(raw) > MAX_JSONL_LINE:
                raise ValueError(f"{path}:{number}: JSONL line exceeds 2 MiB")
            if not raw.strip():
                continue
            try:
                row = strict_json(raw.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: record must be an object")
            yield row


def hash_file(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def source_verdict(source, ledger):
    if not isinstance(source, dict):
        return False, "missing_source"
    if source.get("fixture_only") or not source.get("publication_approved"):
        return False, "not_publication_approved"
    sha = source.get("artifact_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return False, "missing_source_hash"
    if ledger is None:
        return False, "missing_admission_ledger"
    ref = ledger.get(source.get("source_id"))
    if not ref:
        return False, "source_not_admitted"
    # Ledger shape is the existing legal/ledger object; do not infer admission.
    licensed = ref.get("license")
    lic = licensed.get("id") if isinstance(licensed, dict) else ref.get("license_id")
    retrieved = ref.get("retrieval")
    ledger_sha = retrieved.get("sha256") if isinstance(retrieved, dict) else ref.get("artifact_sha256")
    if (ref.get("dataset_version") != source.get("dataset_version") or
            ledger_sha != sha or lic != source.get("license_id")):
        return False, "stale_or_mismatched_provenance"
    if ref.get("admission_status", ref.get("status")) != "approved":
        return False, "source_not_approved_in_ledger"
    return True, "matched"


def issue(db, language, severity, code, kind, rid, detail):
    db.execute("INSERT INTO issue VALUES (?,?,?,?,?,?)",
               (language or "und", severity, code, kind, rid, detail))


def load_snapshot(db, directory, snapshot, ledger):
    for kind, id_field in KINDS.items():
        path = directory / (kind + ".jsonl")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing or unsafe required JSONL file: {path}")
        for item in lines(path):
            rid = item.get(id_field)
            if not isinstance(rid, str) or not rid or len(rid) > 128:
                raise ValueError(f"{path}: missing/invalid {id_field}")
            for field in REQUIRED[kind]:
                if not isinstance(item.get(field), str) or not item[field]:
                    raise ValueError(f"{path}: {rid}: missing/invalid {field}")
            if not isinstance(item.get("source"), dict):
                raise ValueError(f"{path}: {rid}: missing source evidence")
            status, why = source_verdict(item["source"], ledger)
            if snapshot == "current" and item["source"].get("publication_approved") and not status:
                issue(db, item.get("language"), "error", why, kind, rid, "source evidence not admitted")
            if kind == "lexemes":
                pinned = {key: item.get(key) for key in
                          ("language", "script", "lemma", "pos", "dialect", "homograph_key")}
            elif kind == "senses":
                pinned = {key: item[key] for key in ("lexeme_id", "concept_id")}
            elif kind == "translations":
                pinned = {key: item[key] for key in ("from_sense_id", "to_sense_id", "language")}
            elif kind == "relations":
                pinned = {key: item[key] for key in ("from_lexeme_id", "to_lexeme_id", "kind")}
            else:
                pinned = {key: item[key] for key in ("sense_id", "language", "script")}
            values = (
                snapshot, kind, rid, item.get("language"), item.get("script"),
                unicodedata.normalize("NFC", item["lemma"]) if kind == "lexemes" else None,
                item.get("pos"), item.get("dialect") or "", item.get("register") or "",
                item.get("homograph_key") or "",
                item.get("lexeme_id") if kind == "senses" else item.get("sense_id") if kind == "examples" else None,
                item.get("concept_id"), item.get("definition"),
                item.get("from_sense_id", item.get("from_lexeme_id")),
                item.get("to_sense_id", item.get("to_lexeme_id")),
                item.get("language") if kind == "translations" else None,
                canonical(pinned), int(status), canonical(item))
            try:
                db.execute("INSERT INTO rec VALUES (" + ",".join("?" * 19) + ")", values)
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"duplicate {kind} ID in {snapshot}: {rid}") from exc


def analyze_links(db):
    # Stable ID tokens cannot double as another entity type.
    for rid, kinds in db.execute("""SELECT id,GROUP_CONCAT(DISTINCT kind)
        FROM rec WHERE snapshot='current' GROUP BY id
        HAVING COUNT(DISTINCT kind)>1 ORDER BY id"""):
        issue(db, "und", "error", "cross_kind_identity_collision",
              "identity", rid, kinds)
    # Populate derived language, but never derive a sense or translation edge.
    db.execute("""UPDATE rec SET language=(
        SELECT l.language FROM rec l WHERE l.snapshot=rec.snapshot
        AND l.kind='lexemes' AND l.id=rec.parent)
        WHERE kind='senses'""")
    for sid, lex_id in db.execute("""SELECT s.id,s.parent FROM rec s
        LEFT JOIN rec l ON l.snapshot='current' AND l.kind='lexemes' AND l.id=s.parent
        WHERE s.snapshot='current' AND s.kind='senses' AND l.id IS NULL"""):
        issue(db, "und", "error", "orphan_sense", "senses", sid, lex_id)
    for kind in ("translations", "relations", "examples"):
        for rid, left, right, requested, left_lang, right_lang in db.execute("""
          SELECT t.id,t.left_id,t.right_id,t.target_lang,l.language,r.language
          FROM rec t
          LEFT JOIN rec l ON l.snapshot='current'
            AND l.kind=? AND l.id=COALESCE(t.left_id,t.parent)
          LEFT JOIN rec r ON r.snapshot='current' AND r.kind=? AND r.id=t.right_id
          WHERE t.snapshot='current' AND t.kind=?""",
                ("senses" if kind != "relations" else "lexemes",
                 "senses" if kind != "relations" else "lexemes", kind)):
            if kind == "examples":
                # Examples link through the sense, not left_id; check separately below.
                continue
            if not left_lang or not right_lang:
                issue(db, left_lang, "error", "orphan_link", kind, rid, f"{left}|{right}")
            elif kind == "translations" and requested != right_lang:
                issue(db, left_lang, "error", "cross_language_translation", kind, rid,
                      f"expected={right_lang};actual={requested}")
            elif kind == "relations" and left_lang != right_lang:
                issue(db, left_lang, "review", "cross_language_relation", kind, rid,
                      f"to_language={right_lang}")
    for rid, requested, sense_id, linked_lang in db.execute("""
        SELECT e.id,e.language,e.parent,s.language FROM rec e
        LEFT JOIN rec s ON s.snapshot='current' AND s.kind='senses' AND s.id=e.parent
        WHERE e.snapshot='current' AND e.kind='examples'"""):
        if not linked_lang:
            issue(db, requested, "error", "orphan_example", "examples", rid, sense_id)
        elif linked_lang != requested:
            issue(db, requested, "error", "cross_language_example", "examples", rid,
                  f"expected={linked_lang};actual={requested}")
    for rid, lang in db.execute("""SELECT s.id,s.language FROM rec s
        WHERE s.snapshot='current' AND s.kind='senses' AND
        (EXISTS (SELECT 1 FROM rec x WHERE x.snapshot='current' AND
         x.id=s.concept AND x.kind IN ('senses','lexemes')) OR s.id=s.concept)"""):
        issue(db, lang, "error", "concept_identity_collision", "senses", rid, "concept ID reused as entity ID")
    for parent, concept, lang in db.execute("""SELECT parent,concept,MIN(language)
        FROM rec WHERE snapshot='current' AND kind='senses'
        GROUP BY parent,concept HAVING COUNT(DISTINCT definition)>1"""):
        issue(db, lang, "review", "conflicting_concept_definitions", "senses",
              parent + "|" + concept, "same lexeme/concept has differing attested definitions")


def compare_snapshots(db):
    for kind in KINDS:
        query = """SELECT old.id,old.language,old.pinned,new.pinned,
                          old.definition,new.definition
                   FROM rec old LEFT JOIN rec new ON new.snapshot='current'
                     AND new.kind=old.kind AND new.id=old.id
                   WHERE old.snapshot='previous' AND old.kind=? ORDER BY old.id"""
        for rid, lang, old, new, old_def, new_def in db.execute(query, (kind,)):
            if new is None:
                issue(db, lang, "error", "stable_id_removed", kind, rid, "retain previous ID pending review")
            elif old != new:
                issue(db, lang, "error", "stable_id_reassigned", kind, rid, "immutable identity changed")
            elif kind == "senses" and old_def != new_def:
                issue(db, lang, "review", "definition_changed", kind, rid, "source-backed definition changed")


def load_dispositions(db, path):
    if path is None:
        return
    for row in lines(path):
        cid = row.get("candidate_id")
        value = row.get("disposition")
        reviewer, reference = row.get("reviewer"), row.get("review_reference")
        if not all(isinstance(x, str) and x for x in (cid, reviewer, reference)) or value not in DISPOSITIONS:
            raise ValueError("invalid disposition: requires candidate_id, disposition, reviewer, review_reference")
        try:
            db.execute("INSERT INTO review VALUES (?,?,?,?)", (cid, value, reviewer, reference))
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate candidate disposition: " + cid) from exc


def shard_for(identifier, total):
    return int(hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16], 16) % total


def report(db, output, registry, shard, shards, has_previous):
    languages = sorted({row["id"] for row in registry["languages"]})
    metrics = {lang: {"accepted_senses": 0, "total_senses": 0,
                      "unresolved_ambiguity": 0, "reviewer_dispositions": {
                          name: 0 for name in sorted(DISPOSITIONS)}, "conflicts": 0}
               for lang in languages}
    def met(lang):
        return metrics.setdefault(lang or "und", {
            "accepted_senses": 0, "total_senses": 0, "unresolved_ambiguity": 0,
            "reviewer_dispositions": {name: 0 for name in sorted(DISPOSITIONS)}, "conflicts": 0})
    with (output / "conflicts.jsonl").open("w", encoding="utf-8") as handle:
        for lang, severity, code, kind, rid, detail in db.execute("""
           SELECT language,severity,code,kind,id,detail FROM issue
           ORDER BY language,severity,code,kind,id,detail"""):
            if shard_for(kind + ":" + rid, shards) != shard:
                continue
            met(lang)["conflicts"] += 1
            handle.write(canonical({"language": lang, "severity": severity, "code": code,
                                     "kind": kind, "id": rid, "detail": detail}) + "\n")
    with (output / "candidates.jsonl").open("w", encoding="utf-8") as handle:
        for lang, script, lemma, pos, dialect, register, homograph, count in db.execute("""
             SELECT language,script,lemma,pos,dialect,register,homograph,COUNT(*)
             FROM rec WHERE snapshot='current' AND kind='lexemes'
             GROUP BY language,script,lemma,pos,dialect,register,homograph
             HAVING COUNT(*)>1
             ORDER BY language,script,lemma,pos,dialect,register,homograph"""):
            key = [lang, script, lemma, pos, dialect, register, homograph]
            cid = "candidate." + digest(key)
            if shard_for(cid, shards) != shard:
                continue
            rev = db.execute("SELECT disposition,reviewer,reference FROM review WHERE candidate_id=?", (cid,)).fetchone()
            if rev:
                met(lang)["reviewer_dispositions"][rev[0]] += 1
            else:
                met(lang)["unresolved_ambiguity"] += 1
            handle.write(canonical({"record_type": "group", "candidate_id": cid,
                "language": lang, "script": script, "lemma": lemma, "pos": pos,
                "dialect": dialect, "register": register, "homograph_key": homograph,
                "member_count": count, "disposition": rev[0] if rev else "unresolved"}) + "\n")
            for (member,) in db.execute("""SELECT id FROM rec WHERE snapshot='current'
                AND kind='lexemes' AND language=? AND script=? AND lemma=? AND
                pos=? AND dialect=? AND register=? AND homograph=? ORDER BY id""",
                (lang, script, lemma, pos, dialect, register, homograph)):
                handle.write(canonical({"record_type": "member", "candidate_id": cid, "lexeme_id": member}) + "\n")
    with (output / "merge-plan.jsonl").open("w", encoding="utf-8") as handle:
        for kind, rid, lang, source_ok, prior, changed, bad in db.execute("""
            SELECT c.kind,c.id,c.language,
                   CASE WHEN c.kind='senses' THEN
                       MIN(c.source_ok,COALESCE((SELECT l.source_ok FROM rec l
                         WHERE l.snapshot='current' AND l.kind='lexemes' AND l.id=c.parent),0))
                       ELSE c.source_ok END,
                   p.id,
                   CASE WHEN p.id IS NOT NULL AND p.pinned != c.pinned THEN 1 ELSE 0 END,
                   EXISTS(SELECT 1 FROM issue i WHERE i.severity='error' AND
                       ((i.kind=c.kind AND i.id=c.id) OR
                        (c.kind='senses' AND i.kind='lexemes' AND i.id=c.parent)))
            FROM rec c LEFT JOIN rec p ON p.snapshot='previous' AND p.kind=c.kind AND p.id=c.id
            WHERE c.snapshot='current' AND c.kind IN ('lexemes','senses')
            ORDER BY c.kind,c.id"""):
            if shard_for(kind + ":" + rid, shards) != shard:
                continue
            if prior:
                action = "retain_id_review" if changed or bad else "retain_id"
            else:
                action = "review_new" if bad or not source_ok else "propose_add_only"
            handle.write(canonical({"kind": kind, "id": rid, "language": lang or "und",
                                    "action": action, "canonical_write": False}) + "\n")
        if has_previous:
            for kind, rid, lang in db.execute("""
                SELECT p.kind,p.id,p.language FROM rec p LEFT JOIN rec c
                ON c.snapshot='current' AND c.kind=p.kind AND c.id=p.id
                WHERE p.snapshot='previous' AND p.kind IN ('lexemes','senses')
                AND c.id IS NULL ORDER BY p.kind,p.id"""):
                if shard_for(kind + ":" + rid, shards) == shard:
                    handle.write(canonical({"kind": kind, "id": rid, "language": lang or "und",
                                            "action": "retain_previous_missing",
                                            "canonical_write": False}) + "\n")
    for sid, lang, approved, lex_approved, failure in db.execute("""
        SELECT s.id,s.language,s.source_ok,l.source_ok,
          EXISTS(SELECT 1 FROM issue i WHERE i.severity='error' AND
            ((i.kind='senses' AND i.id=s.id) OR (i.kind='lexemes' AND i.id=s.parent)))
        FROM rec s LEFT JOIN rec l ON l.snapshot='current' AND l.kind='lexemes' AND l.id=s.parent
        WHERE s.snapshot='current' AND s.kind='senses' ORDER BY s.id"""):
        if shard_for("senses:" + sid, shards) != shard:
            continue
        met(lang)["total_senses"] += 1
        if approved and lex_approved and not failure:
            met(lang)["accepted_senses"] += 1
    (output / "per-language.json").write_text(canonical({
        "shard": shard, "shards": shards, "languages": metrics}) + "\n", encoding="utf-8")


def inventory(input_dir, previous, ledger, dispositions, registry):
    paths = []
    for directory in (input_dir, previous):
        if directory:
            paths.extend(directory / (kind + ".jsonl") for kind in KINDS)
    paths.extend(p for p in (ledger, dispositions, registry) if p)
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing or unsafe input: {path}")
    return {str(path.resolve()): hash_file(path) for path in sorted(paths)}


def audit(input_dir, out_dir, *, previous=None, ledger=None, dispositions=None,
          registry=None, shard=0, shards=1, resume=False):
    input_dir, out_dir = Path(input_dir), Path(out_dir)
    previous = Path(previous) if previous else None
    ledger = Path(ledger) if ledger else None
    dispositions = Path(dispositions) if dispositions else None
    registry = Path(registry) if registry else None
    if not 1 <= shards <= 256 or not 0 <= shard < shards:
        raise ValueError("invalid bounded shard selection")
    if registry is None:
        raise ValueError("100-language registry is mandatory")
    inputs = inventory(input_dir, previous, ledger, dispositions, registry)
    parameters = {"inputs": inputs, "shard": shard, "shards": shards, "tool_version": 1}
    fingerprint = digest(parameters)
    if out_dir.exists():
        if not resume:
            raise FileExistsError("output exists; pass --resume to verify exact immutable checkpoint")
        checkpoint = strict_json((out_dir / "checkpoint.json").read_text(encoding="utf-8"))
        if checkpoint.get("fingerprint") != fingerprint or any(
                hash_file(out_dir / name) != sha for name, sha in checkpoint["outputs"].items()):
            raise ValueError("stale/corrupted checkpoint; refusing replay")
        return checkpoint
    registry_doc = strict_json(registry.read_text(encoding="utf-8"))
    if len(registry_doc.get("languages", [])) != 100 or len({
            x["id"] for x in registry_doc["languages"]}) != 100:
        raise ValueError("canonical registry must contain exactly 100 unique language IDs")
    ledger_doc = strict_json(ledger.read_text(encoding="utf-8")) if ledger else None
    if ledger_doc is not None and not isinstance(ledger_doc.get("sources"), list):
        raise ValueError("expected legal source ledger with sources array")
    ledger_index = {} if ledger_doc is not None else None
    if ledger_doc:
        for source in ledger_doc["sources"]:
            sid = source.get("source_id")
            if not isinstance(sid, str) or sid in ledger_index:
                raise ValueError("duplicate/invalid source in legal ledger")
            ledger_index[sid] = source
    with tempfile.TemporaryDirectory(prefix=".sense_integrity-", dir=out_dir.parent) as temp:
        temp_dir = Path(temp)
        conn = sqlite3.connect(temp_dir / "work.sqlite")
        conn.executescript(DDL)
        try:
            if previous:
                load_snapshot(conn, previous, "previous", ledger_index)
            load_snapshot(conn, input_dir, "current", ledger_index)
            load_dispositions(conn, dispositions)
            analyze_links(conn)
            if previous:
                compare_snapshots(conn)
            reports = temp_dir / "reports"
            reports.mkdir()
            report(conn, reports, registry_doc, shard, shards, previous is not None)
        finally:
            conn.close()
        outputs = {path.name: hash_file(path) for path in sorted(reports.iterdir())}
        checkpoint = {"fingerprint": fingerprint, "outputs": outputs,
                      "input_hashes": inputs, "shard": shard, "shards": shards,
                      "status": "QA_ONLY_NOT_PUBLICATION_APPROVAL"}
        (reports / "checkpoint.json").write_text(canonical(checkpoint) + "\n", encoding="utf-8")
        reports.rename(out_dir)
    return checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--previous-dir", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--dispositions", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        checkpoint = audit(args.input_dir, args.out_dir, previous=args.previous_dir,
            ledger=args.ledger, dispositions=args.dispositions, registry=args.registry,
            shard=args.shard, shards=args.shards, resume=args.resume)
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as exc:
        print(f"SENSE_INTEGRITY_INVALID: {exc}", file=sys.stderr)
        return 2
    print(canonical({"status": checkpoint["status"], "fingerprint": checkpoint["fingerprint"],
                     "out_dir": str(args.out_dir), "shard": args.shard, "shards": args.shards}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
