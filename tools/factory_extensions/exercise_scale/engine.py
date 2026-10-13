"""Fail-closed evidence QA for offline language exercise candidates (no publication)."""
import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

TYPES = {"recognition", "recall", "multiple_choice", "cloze", "matching",
         "spelling", "verb_conjugation", "grammar"}
DIFFICULTIES = {"beginner", "intermediate", "advanced"}
SHA = re.compile(r"^[0-9a-f]{64}$")
REQUIRED = {"schema_version", "type", "language", "source_language",
    "target_language", "interface_language", "script", "directed_pair_id",
    "source_sense_id", "sense_id", "lexeme_id", "grammar_rule_id",
    "proficiency", "difficulty", "prompt", "correct_answers",
    "ambiguous_answers", "answer_policy", "choices", "matching_pairs",
    "features", "cloze_source", "cloze_span", "evidence", "review",
    "explanation", "fixture_only", "publication_approved"}


class ExerciseError(ValueError):
    """Unsupported or conflicting educational evidence."""


def fail(code):
    raise ExerciseError(code)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 2000 and bool(value.strip()) and not any(
        unicodedata.category(x) in ("Cc", "Cs") for x in value)


def _texts(values, empty=False):
    return isinstance(values, list) and (empty or bool(values)) and len(values) <= 16 and all(
        _text(v) for v in values)


def _nfc(value):
    return unicodedata.normalize("NFC", value)


def grade_response(response, accepted, attested_alternates, diacritics="strict"):
    """Never strip diacritics; only explicitly accepted variants are correct."""
    if (not isinstance(response, str) or not _texts(accepted)
            or not _texts(attested_alternates, empty=True)
            or diacritics not in ("strict", "explicit_variants")):
        fail("INVALID_ANSWER_POLICY")
    good, ambiguous = set(map(_nfc, accepted)), set(map(_nfc, attested_alternates))
    if good & ambiguous:
        fail("CONTRADICTORY_ANSWER_EVIDENCE")
    if _nfc(response) in good:
        return "CORRECT"
    if _nfc(response) in ambiguous:
        return "AMBIGUOUS"
    return "UNVERIFIED"


def _source(record, refs):
    evidence = record.get("evidence")
    if not isinstance(evidence, dict):
        fail("SOURCE_NOT_APPROVED")
    src = refs.get("sources", {}).get(evidence.get("source_id"))
    if not isinstance(src, dict) or src.get("status") != "APPROVED_FOR_REDISTRIBUTION":
        fail("SOURCE_NOT_APPROVED")
    lic = src.get("license_id")
    if lic is None and isinstance(src.get("license"), dict):
        lic = src["license"].get("id")
    sha = src.get("artifact_sha256")
    if sha is None and isinstance(src.get("retrieval"), dict):
        sha = src["retrieval"].get("sha256")
    for key, expected in (("publisher", src.get("publisher")),
                          ("dataset_version", src.get("dataset_version")),
                          ("license_id", lic), ("artifact_sha256", sha)):
        if not isinstance(expected, str) or evidence.get(key) != expected:
            fail("SOURCE_PROVENANCE_MISMATCH")
    if (not SHA.fullmatch(evidence["artifact_sha256"])
            or not SHA.fullmatch(str(evidence.get("record_sha256", "")))
            or not _text(evidence.get("locator")) or not _url(evidence.get("origin_url"))
            or not _url(evidence.get("answer_evidence_url"))):
        fail("MISSING_RECORD_EVIDENCE")
    if src.get("origin_url") is not None and evidence["origin_url"] != src["origin_url"]:
        fail("SOURCE_PROVENANCE_MISMATCH")


def _sense(refs, sid, language, lexeme=None):
    s = refs.get("senses", {}).get(sid)
    if (not isinstance(s, dict) or s.get("approved") is not True
            or s.get("language") != language
            or (lexeme is not None and s.get("lexeme_id") != lexeme)):
        fail("LEXICAL_SENSE_EVIDENCE_REQUIRED")


def _direction(c, refs):
    a, b = c["source_language"], c["target_language"]
    if a == b:
        if c["directed_pair_id"] is not None or c["source_sense_id"] is not None:
            fail("DIRECTION_EVIDENCE_MISMATCH")
        return
    _sense(refs, c["source_sense_id"], a)
    pair = refs.get("pairs", {}).get(c["directed_pair_id"])
    if (not isinstance(pair, dict) or pair.get("approved") is not True
            or any(pair.get(k) != v for k, v in (
                ("source_language", a), ("target_language", b),
                ("source_sense_id", c["source_sense_id"]),
                ("target_sense_id", c["sense_id"])))
            or not _url(pair.get("translation_evidence_url"))):
        fail("DIRECTION_EVIDENCE_MISMATCH")


def _grammar(c, refs):
    rule_id = c["grammar_rule_id"]
    if rule_id is None:
        if c["explanation"] is not None or c["type"] in ("grammar", "verb_conjugation"):
            fail("GRAMMAR_EVIDENCE_REQUIRED")
        return
    rule = refs.get("rules", {}).get(rule_id)
    if (not isinstance(rule, dict) or rule.get("approved") is not True
            or rule.get("language") != c["target_language"]):
        fail("GRAMMAR_EVIDENCE_REQUIRED")
    if c["explanation"] is not None and c["explanation"] != rule.get("explanation"):
        fail("UNAPPROVED_GRAMMAR_EXPLANATION")


def _choice_qa(c, refs):
    opts = c["choices"]
    if not isinstance(opts, list):
        fail("INVALID_CHOICES")
    if c["type"] != "multiple_choice":
        if opts:
            fail("UNEXPECTED_CHOICES")
        return
    if len(opts) not in range(3, 7) or c["review"].get("distractors_reviewed") is not True:
        fail("DISTRACTOR_NOT_ATTESTED")
    seen, hits = set(), 0
    answers = {_nfc(a) for a in c["correct_answers"]}
    for option in opts:
        if not isinstance(option, dict) or set(option) != {"text", "evidence_id"}:
            fail("INVALID_CHOICES")
        word = option["text"]
        if not _text(word) or _nfc(word).casefold() in seen:
            fail("DUPLICATE_OR_EQUIVALENT_CHOICES")
        seen.add(_nfc(word).casefold())
        if _nfc(word) in answers:
            hits += 1
            continue
        item = refs.get("distractors", {}).get(option["evidence_id"])
        if (not isinstance(item, dict) or item.get("approved") is not True
                or (item.get("language"), item.get("text")) != (c["target_language"], word)
                or not _url(item.get("not_equivalent_review_url"))):
            fail("DISTRACTOR_NOT_ATTESTED")
    if hits != 1 or any(_nfc(v) in {_nfc(o["text"]) for o in opts} for v in c["ambiguous_answers"]):
        fail("AMBIGUOUS_CORRECT_CHOICES")


def _matching(c, refs):
    pairs = c["matching_pairs"]
    if not isinstance(pairs, list):
        fail("INVALID_MATCHING")
    if c["type"] != "matching":
        if pairs:
            fail("UNEXPECTED_MATCHING")
        return
    if not 2 <= len(pairs) <= 8:
        fail("INVALID_MATCHING")
    left, right, ids = set(), set(), set()
    for p in pairs:
        if not isinstance(p, dict) or set(p) != {"left", "right", "edge_id"}:
            fail("INVALID_MATCHING")
        edge = refs.get("pairs", {}).get(p["edge_id"])
        if (not _text(p["left"]) or not _text(p["right"])
                or not isinstance(edge, dict) or edge.get("approved") is not True
                or (edge.get("source_language"), edge.get("target_language")) !=
                    (c["source_language"], c["target_language"])
                or (edge.get("source_text"), edge.get("target_text")) != (p["left"], p["right"])):
            fail("MATCHING_EDGE_NOT_ATTESTED")
        if _nfc(p["left"]) in left or _nfc(p["right"]) in right or p["edge_id"] in ids:
            fail("AMBIGUOUS_MATCHING")
        left.add(_nfc(p["left"])); right.add(_nfc(p["right"])); ids.add(p["edge_id"])


def validate_candidate(c, refs):
    """Validate a preauthored exercise without generating any linguistic facts."""
    if not isinstance(c, dict) or set(c) - (REQUIRED | {"form_evidence_id"}) or not REQUIRED <= set(c):
        fail("INVALID_EXERCISE_CONTRACT")
    if c["schema_version"] != "1.0.0" or c["type"] not in TYPES:
        fail("INVALID_EXERCISE_CONTRACT")
    languages = refs.get("languages", {})
    for key in ("language", "source_language", "target_language", "interface_language"):
        if c[key] not in languages:
            fail("UNREGISTERED_LANGUAGE")
    if c["language"] != c["target_language"]:
        fail("TARGET_LANGUAGE_MISMATCH")
    if c["script"] not in languages[c["language"]].get("scripts", []):
        fail("SCRIPT_MISMATCH")
    if (c["difficulty"] not in DIFFICULTIES or type(c["fixture_only"]) is not bool
            or type(c["publication_approved"]) is not bool or not _text(c["prompt"])
            or not isinstance(c["features"], dict) or
            any(not _text(k) or not _text(v) for k, v in c["features"].items())):
        fail("INVALID_EXERCISE_CONTRACT")
    answers, alternatives = c["correct_answers"], c["ambiguous_answers"]
    if not _texts(answers, empty=c["type"] == "matching") or not _texts(alternatives, empty=True):
        fail("INVALID_ANSWER_EVIDENCE")
    policy = c["answer_policy"]
    if (not isinstance(policy, dict) or set(policy) != {"unicode", "diacritics"}
            or policy["unicode"] != "NFC" or policy["diacritics"] not in ("strict", "explicit_variants")):
        fail("INVALID_ANSWER_POLICY")
    if c["type"] != "matching":
        grade_response(answers[0], answers, alternatives, policy["diacritics"])
    review = c["review"]
    if (not isinstance(review, dict) or review.get("approved") is not True
            or not _text(review.get("reviewer_id")) or not _url(review.get("decision_url"))
            or review.get("answer_unambiguous") is not True):
        fail("EDITORIAL_REVIEW_REQUIRED")
    _source(c, refs)
    _sense(refs, c["sense_id"], c["target_language"], c["lexeme_id"])
    _direction(c, refs)
    prof = c["proficiency"]
    if not isinstance(prof, dict) or set(prof) != {"framework_id", "level_id", "evidence_id"}:
        fail("PROFICIENCY_EVIDENCE_REQUIRED")
    trusted = refs.get("proficiency", {}).get(prof["evidence_id"])
    if (not isinstance(trusted, dict) or trusted.get("approved") is not True
            or any(trusted.get(k) != v for k, v in (("language", c["target_language"]),
                ("framework_id", prof["framework_id"]), ("level_id", prof["level_id"])))):
        fail("PROFICIENCY_EVIDENCE_MISMATCH")
    _grammar(c, refs)
    _choice_qa(c, refs)
    _matching(c, refs)
    if c["type"] == "cloze":
        source, span = c["cloze_source"], c["cloze_span"]
        if (not _text(source) or not isinstance(span, list) or len(span) != 2
                or any(type(i) is not int for i in span)
                or not 0 <= span[0] < span[1] <= len(source)):
            fail("INVALID_CLOZE_SPAN")
        if _hash(source.encode("utf-8")) != c["evidence"]["record_sha256"]:
            fail("SOURCE_TEXT_HASH_MISMATCH")
        word = source[span[0]:span[1]]
        if (word not in answers or source.count(word) != 1 or
                c["prompt"] != source[:span[0]] + "____" + source[span[1]:]):
            fail("CLOZE_ANSWER_MISMATCH")
    elif c["cloze_source"] is not None or c["cloze_span"] is not None:
        fail("UNEXPECTED_CLOZE_EVIDENCE")
    if c["type"] == "verb_conjugation":
        form = refs.get("forms", {}).get(c.get("form_evidence_id"))
        if (not isinstance(form, dict) or form.get("approved") is not True or
                (form.get("language"), form.get("sense_id")) !=
                (c["target_language"], c["sense_id"]) or
                form.get("text") not in answers or form.get("features") != c["features"]):
            fail("ATTESTED_FORM_REQUIRED")
    elif c.get("form_evidence_id") is not None:
        fail("UNEXPECTED_FORM_EVIDENCE")
    if c["type"] not in ("cloze", "matching") and any(
            _nfc(answer).casefold() in _nfc(c["prompt"]).casefold() for answer in answers):
        fail("ANSWER_LEAK_OR_TRIVIAL")
    if c["type"] == "cloze" and not c["prompt"].replace("____", "").strip():
        fail("ANSWER_LEAK_OR_TRIVIAL")
    return {"candidate_sha256": _hash(canonical(c)), "language": c["target_language"],
            "exercise_type": c["type"], "difficulty": c["difficulty"],
            "status": "REVIEW_REQUIRED", "publication_approved": False,
            "fixture_only": c["fixture_only"]}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_partition(path, declared_sha256, refs, *, max_records=100000):
    """Replay immutable JSONL, use temporary disk-based duplicate index."""
    if not isinstance(declared_sha256, str) or not SHA.fullmatch(declared_sha256):
        fail("INPUT_SHA256_MISMATCH")
    if sha_file(path) != declared_sha256:
        fail("INPUT_SHA256_MISMATCH")
    counts = {language: {} for language in sorted(refs["languages"])}
    by_type, slots = Counter(), Counter()
    records = 0
    with tempfile.TemporaryDirectory(prefix="exercises-qa-") as temp:
        with sqlite3.connect(str(Path(temp) / "seen.sqlite")) as db:
            db.execute("CREATE TABLE seen (key TEXT PRIMARY KEY)")
            with Path(path).open("rb") as handle:
                for line_no, raw in enumerate(handle, 1):
                    if line_no > max_records or len(raw) > 1048576:
                        fail("PARTITION_BOUNDS_EXCEEDED")
                    try:
                        c = json.loads(raw.decode("utf-8"),
                                       object_pairs_hook=_unique_pairs,
                                       parse_constant=lambda _: fail("INVALID_JSONL"))
                    except (UnicodeError, ValueError) as exc:
                        raise ExerciseError("INVALID_JSONL") from exc
                    result = validate_candidate(c, refs)
                    fingerprint = _hash(canonical([c["type"], c["target_language"],
                        c["sense_id"], c["prompt"], c["correct_answers"], c["matching_pairs"]]))
                    try:
                        db.execute("INSERT INTO seen VALUES (?)", (fingerprint,))
                    except sqlite3.IntegrityError as exc:
                        raise ExerciseError("DUPLICATE_EXERCISE") from exc
                    lang, kind, difficulty = (result["language"], result["exercise_type"],
                                              result["difficulty"])
                    counts[lang].setdefault(kind, {}).setdefault(difficulty, 0)
                    counts[lang][kind][difficulty] += 1
                    records += 1
                    by_type[kind] += 1
                    if kind == "multiple_choice":
                        for index, option in enumerate(c["choices"]):
                            if option["text"] in c["correct_answers"]:
                                slots[index] += 1
                                break
    if by_type["multiple_choice"] >= 4 and max(slots.values(), default=0) == by_type["multiple_choice"]:
        fail("REPEATED_ANSWER_POSITION")
    return {"schema_version": "1.0.0", "status": "REVIEW_REQUIRED_NOT_PUBLISHED",
            "immutable_input_sha256": declared_sha256,
            "checkpoint_sha256": _hash(canonical([declared_sha256, counts])),
            "records_processed": records, "candidates_review_required": records,
            "verified_exercises": 0, "publication_approved": False,
            "count_by_language": counts, "count_by_type": dict(sorted(by_type.items()))}


def catalog_references(root):
    root = Path(root)
    catalog = json.loads((root / "catalog/language_registry.v1.json").read_text(encoding="utf-8"))
    ledger = json.loads((root / "legal/ledger/sources.json").read_text(encoding="utf-8"))
    if (catalog.get("schema_version") != "1.0.0" or len(catalog.get("languages", [])) != 100
            or ledger.get("schema_version") != "1.0.0"):
        fail("CANONICAL_CONTRACT_MISMATCH")
    languages = {c["id"]: {"scripts": c["scripts"]} for c in catalog["languages"]}
    sources = {c["source_id"]: c for c in ledger.get("sources", [])}
    if len(sources) != len(ledger.get("sources", [])):
        fail("DUPLICATE_LEDGER_ID")
    return {"languages": languages, "sources": sources, "senses": {},
            "pairs": {}, "forms": {}, "rules": {}, "proficiency": {},
            "distractors": {}}


def main(argv=None):
    cli = argparse.ArgumentParser(description="Read-only evidence exercise audit")
    cli.add_argument("--repo-root", default=".")
    cli.add_argument("--input", type=Path)
    cli.add_argument("--input-sha256")
    cli.add_argument("--references", type=Path)
    cli.add_argument("--report", type=Path)
    args = cli.parse_args(argv)
    refs = catalog_references(args.repo_root)
    if args.input:
        if not args.references or not args.input_sha256:
            fail("MISSING_IMMUTABLE_INPUT_OR_REFERENCES")
        supplied = json.loads(args.references.read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_pairs)
        for name in ("senses", "pairs", "forms", "rules", "proficiency", "distractors"):
            refs[name] = supplied.get(name, {})
        result = audit_partition(args.input, args.input_sha256, refs)
    else:
        if args.references or args.input_sha256:
            fail("MISSING_IMMUTABLE_INPUT")
        result = {
            "status": "BLOCKED_SOURCE", "registered_languages": len(refs["languages"]),
            "approved_source_count": sum(c.get("status") == "APPROVED_FOR_REDISTRIBUTION"
                for c in refs["sources"].values()), "verified_exercises": 0,
            "dispatched_run_ids": [], "count_by_language":
                {lang: {} for lang in sorted(refs["languages"])},
            "reason": "No independently approved immutable exercise partition",
        }
    output = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report:
        args.report.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
