#!/usr/bin/env python3
"""European morphology evidence contracts; no generation, no cross-language transfer.

Production requires Route05 admission and exact immutable SHA-named input shards.
Python standard library only. All outputs are evidence-classified, not pack releases.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unicodedata

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
STATUSES = ("verified", "predicted", "gap", "disagreement")
MAX_LINE = 65536
MAX_SHARD = 64 * 1024 * 1024
DIMENSIONS = ("case", "gender", "number", "animacy", "aspect", "mutation",
              "construction", "stress")
PROFILE_KEYS = {"case": "cases", "gender": "genders", "number": "numbers",
                "animacy": "animacy", "aspect": "aspects", "mutation": "mutations",
                "construction": "constructions", "stress": "stress_modes"}
FREE_TAGS = {"tense", "mood", "person", "voice", "conjugation_class",
             "pronunciation_note", "orthographic_note", "stress_note",
             "mutation_trigger"}
AGREEMENT = {"agreement_case": "cases", "agreement_gender": "genders",
             "agreement_number": "numbers"}
REQUIRED = {"record_id", "language_code", "lemma_id", "sense_id", "lemma", "form",
            "script", "category", "features", "evidence_status",
            "paradigm_complete", "source_refs"}
OPTIONAL = {"gap_note", "prediction_note", "disagreement_note",
            "orthographic_variant_of"}
PROFILES = json.loads((BASE / "profiles.json").read_text(encoding="utf-8"))["independent_language_profiles"]


class ContractError(ValueError):
    """Strict evidence, identity, script, or admissibility violation."""


def loads_unique(text):
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ContractError("duplicate JSON key: " + key)
            data[key] = value
        return data
    try:
        return json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise ContractError("invalid JSON: " + str(exc)) from exc


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(value, name, allow_empty=False):
    if not isinstance(value, str) or len(value) > 1024 or (
            not allow_empty and (not value or value != value.strip())):
        raise ContractError(name + ": nonempty, unpadded string required")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs") for ch in value):
        raise ContractError(name + ": control or bidirectional format codepoint")
    if unicodedata.normalize("NFC", value) != value:
        raise ContractError(name + ": noncanonical Unicode NFC")
    return value


def _script(value, script, label):
    _text(value, label)
    prefixes = {"Latn": "LATIN", "Cyrl": "CYRILLIC", "Grek": "GREEK"}
    prefix = prefixes[script]
    letters = 0
    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            letters += 1
            if not unicodedata.name(ch, "").startswith(prefix):
                raise ContractError(label + ": letter from wrong script")
        elif cat.startswith("M"):
            if not letters:
                raise ContractError(label + ": orphan combining mark")
        elif cat.startswith("N") or cat.startswith("P") or cat == "Zs":
            continue
        else:
            raise ContractError(label + ": unexpected codepoint")
    if letters == 0:
        raise ContractError(label + ": no letters")
    return value


def validate_profiles(root=ROOT):
    root = Path(root)
    registry = loads_unique((root / "catalog/language_registry.v1.json").read_text(encoding="utf-8"))
    manifest = loads_unique((root / "manifest.json").read_text(encoding="utf-8"))
    overrides = loads_unique((root / "standards/morphology/feature_overrides.json").read_text(encoding="utf-8"))
    public_form = loads_unique((root / "standards/morphology/form.schema.json").read_text(encoding="utf-8"))
    if not {"language_code", "lemma_id", "sense_id", "source_id", "evidence_version"}.issubset(
            public_form.get("properties", {})):
        raise ContractError("public morphology form identity contract unavailable")
    languages = registry.get("languages")
    published = manifest.get("languages")
    if not isinstance(languages, list) or not isinstance(published, list) or len(published) != 100:
        raise ContractError("canonical 100-language registration unavailable")
    indexed = {x["id"]: x for x in languages}
    published_ids = {x["code"]: x for x in published}
    if len(indexed) != len(languages) or len(published_ids) != 100:
        raise ContractError("duplicate canonical language identities")
    expected = {code for code, item in published_ids.items()
                if item.get("family") in {"Slavic", "Hellenic", "Baltic", "Celtic"}}
    if set(PROFILES) != expected or len(PROFILES) != 19 or not expected.issubset(indexed):
        raise ContractError("incomplete or stale registered European language roster")
    if not {"case", "grammatical_gender", "aspect", "agreement",
            "orthographic_variants"}.issubset(overrides.get("features", [])):
        raise ContractError("public morphology capability dimensions unavailable")
    for lang, profile in PROFILES.items():
        source = indexed[lang]
        if profile["family"] != source["family"] or profile["family"] != published_ids[lang]["family"]:
            raise ContractError(lang + ": family identity mismatch")
        if profile["scripts"] != source["scripts"]:
            raise ContractError(lang + ": scripts differ from canonical registry")
        if not profile["scripts"] or not set(profile["scripts"]).issubset({"Latn", "Cyrl", "Grek"}):
            raise ContractError(lang + ": unsupported script")
        if set(profile) != {"family", "scripts", "cases", "genders", "numbers", "animacy",
                            "aspects", "mutations", "constructions", "stress_modes"}:
            raise ContractError(lang + ": incomplete independent profile")
        for dimension in PROFILE_KEYS.values():
            values = profile[dimension]
            if not isinstance(values, list) or len(values) != len(set(values)):
                raise ContractError(lang + ": invalid independent dimension " + dimension)
    return True


def source_gate(source_id, version, checksum, allowed_sources):
    _text(source_id, "source_id")
    _text(version, "dataset_version")
    source = allowed_sources.get(source_id)
    if source is None or source.get("kind") != "morphology" or (
            source.get("status") != "APPROVED_FOR_REDISTRIBUTION"):
        raise ContractError("BLOCKED_SOURCE: no approved morphology source " + source_id)
    if not isinstance(checksum, str) or len(checksum) != 64 or any(
            c not in "0123456789abcdef" for c in checksum):
        raise ContractError("invalid source SHA-256")
    if source.get("dataset_version") != version or (
            source.get("retrieval") or {}).get("sha256") != checksum:
        raise ContractError("BLOCKED_SOURCE: source version or snapshot SHA mismatch")


def validate_record(record, allowed_sources):
    if not isinstance(record, dict) or set(record) - REQUIRED - OPTIONAL or not REQUIRED.issubset(record):
        raise ContractError("missing or unknown evidence record fields")
    lang = record["language_code"]
    if lang not in PROFILES:
        raise ContractError("unregistered European language identity")
    profile = PROFILES[lang]
    for field in ("record_id", "lemma_id", "sense_id"):
        identity = _text(record[field], field)
        if not identity.startswith(lang + ":") or len(identity) <= len(lang) + 1:
            raise ContractError(field + ": identity cannot cross a language")
    if record["script"] not in profile["scripts"]:
        raise ContractError(lang + ": unsupported orthography script")
    _script(record["lemma"], record["script"], "lemma")
    status = record["evidence_status"]
    if status not in STATUSES:
        raise ContractError("unknown evidence status")
    if not isinstance(record["form"], str):
        raise ContractError("form: a string is required even for gaps")
    if status == "verified" or record["form"]:
        _script(record["form"], record["script"], "form")
    if record["category"] not in ("noun", "verb", "adjective", "construction"):
        raise ContractError("invalid linguistic category")
    if record["paradigm_complete"] is not False:
        raise ContractError("complete paradigm assertion forbidden")
    if "orthographic_variant_of" in record:
        identity = _text(record["orthographic_variant_of"], "orthographic_variant_of")
        if not identity.startswith(lang + ":"):
            raise ContractError("orthographic variant references another language")
        if identity == record["record_id"]:
            raise ContractError("orthographic variant self-reference")
    tags = record["features"]
    if not isinstance(tags, dict) or not set(tags).issubset(
            set(DIMENSIONS) | FREE_TAGS | set(AGREEMENT) | {"accent"}):
        raise ContractError("unknown or malformed morphology features")
    for tag, value in tags.items():
        _text(value, "feature " + tag)
        if tag in PROFILE_KEYS and value not in profile[PROFILE_KEYS[tag]]:
            raise ContractError(lang + ": foreign or unsupported feature " + tag + "/" + value)
        if tag in AGREEMENT and value not in profile[AGREEMENT[tag]]:
            raise ContractError(lang + ": invalid adjective agreement " + tag)
    if "mutation" in tags and not tags.get("mutation_trigger"):
        raise ContractError("mutation requires explicit source-backed trigger")
    if "mutation_trigger" in tags and "mutation" not in tags:
        raise ContractError("mutation trigger without verified mutation feature")
    if "accent" in tags:
        if lang != "el" or tags["accent"] not in ("marked", "unmarked"):
            raise ContractError("accent evidence is Greek-specific")
        decomposed = unicodedata.normalize("NFD", record["form"])
        marked = any(ch in ("\u0300", "\u0301", "\u0342") for ch in decomposed)
        if marked != (tags["accent"] == "marked"):
            raise ContractError("Greek accent evidence contradicts exact spelling")
    if any(x in tags for x in AGREEMENT) and record["category"] not in ("adjective", "construction"):
        raise ContractError("adjective agreement outside adjective/construction")
    requirements = {"predicted": "prediction_note", "gap": "gap_note",
                    "disagreement": "disagreement_note"}
    if status in requirements:
        _text(record.get(requirements[status]), requirements[status])
    sources = record["source_refs"]
    if not isinstance(sources, list) or not sources:
        raise ContractError("missing exact per-record source evidence")
    identifiers = set()
    for ref in sources:
        if not isinstance(ref, dict) or set(ref) != {
                "source_id", "dataset_version", "artifact_sha256", "locator"}:
            raise ContractError("incomplete source reference")
        _text(ref["locator"], "source locator")
        sid = ref["source_id"]
        if sid in identifiers:
            raise ContractError("duplicate source reference")
        identifiers.add(sid)
        source_gate(sid, ref["dataset_version"], ref["artifact_sha256"], allowed_sources)
    if status == "disagreement" and len(identifiers) < 2:
        raise ContractError("source disagreement requires two independent sources")
    return record


def to_public_morphology_form(record, allowed_sources, root=ROOT):
    """Adapter only when every used public capability is explicitly supported.

    Celtic mutation, source-specific stress/accent and constructions have no
    public v1 feature mapping, so they never silently pass through.
    """
    validate_record(record, allowed_sources)
    if record["evidence_status"] != "verified" or len(record["source_refs"]) != 1:
        raise ContractError("public form requires singular verified attestation")
    translated = {}
    aliases = {"gender": "grammatical_gender"}
    public = loads_unique((Path(root) / "standards/morphology/feature_overrides.json").read_text(encoding="utf-8"))
    status = public["overrides"].get(record["language_code"], {})
    for feature, value in record["features"].items():
        public_feature = aliases.get(feature, feature)
        if public_feature not in public["features"] or status.get(public_feature) != "supported":
            raise ContractError("public morphology capability unknown or not supported: " + public_feature)
        translated[public_feature] = value
    ref = record["source_refs"][0]
    return {"language_code": record["language_code"],
            "lemma_id": record["lemma_id"], "sense_id": record["sense_id"],
            "lemma": record["lemma"], "form": record["form"],
            "features": translated, "script": record["script"],
            "source_id": ref["source_id"], "evidence_version": ref["dataset_version"]}


def _load_admission(root):
    root = Path(root)
    location = root / "legal/ledger/admission.py"
    spec = importlib.util.spec_from_file_location("_route05_european", location)
    if spec is None or spec.loader is None:
        raise ContractError("Route05 admission gate not available")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ledger = loads_unique((root / "legal/ledger/sources.json").read_text(encoding="utf-8"))
    manifest = loads_unique((root / "manifest.json").read_text(encoding="utf-8"))
    dailies = [loads_unique(p.read_text(encoding="utf-8"))
               for p in sorted((root / "legal/ledger/daily").glob("*.json"))]
    issues = module.evaluate(ledger, manifest, dailies, root)
    if issues:
        raise ContractError("BLOCKED_SOURCE: Route05 rejected evidence: " + "; ".join(issues[:5]))
    return {s["source_id"]: s for s in ledger["sources"] if isinstance(s, dict) and "source_id" in s}


def _counters():
    return {s: 0 for s in STATUSES}


def summarize(rows, allowed_sources):
    counts = _counters()
    verified = []
    for row in rows:
        valid = validate_record(row, allowed_sources)
        counts[valid["evidence_status"]] += 1
        if valid["evidence_status"] == "verified":
            verified.append(valid)
    return {"counts": counts, "verified": verified}


def _atomic_write(path, content):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".inflection-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
        if path.exists() and sha256_file(path) != sha256_file(temp):
            raise ContractError("immutable output collision: " + path.name)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _json_bytes(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def process_shards(root=ROOT, shards_dir=None, output_dir=None):
    root = Path(root).resolve()
    validate_profiles(root)
    base = root / "tools/linguistic_extensions/european_inflection/shards"
    shards_dir = Path(shards_dir or base)
    output_dir = Path(output_dir or tempfile.mkdtemp(prefix="european-inflection-"))
    report = {"schema_version": "1.0.0",
              "status": "BLOCKED_NO_ADMITTED_SHARDS", "total": 0,
              "languages": {lang: _counters() for lang in sorted(PROFILES)},
              "shards": []}
    paths = sorted(shards_dir.glob("*.jsonl")) if shards_dir.exists() else []
    if not paths:
        return report
    if not shards_dir.resolve().is_relative_to(base.resolve()) or shards_dir.is_symlink():
        raise ContractError("shard input outside isolated approved scope")
    allowed_sources = _load_admission(root)
    if not allowed_sources:
        raise ContractError("BLOCKED_SOURCE: no Route05-approved morphology dataset")
    if output_dir.exists():
        raise ContractError("immutable run output path already exists; choose a fresh path")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after every source, record, and shard passes. Never leak partial
    # verified streams if a later shard fails validation.
    with tempfile.TemporaryDirectory(prefix=".european-inflection-", dir=output_dir.parent) as scratch_dir:
        staged = Path(scratch_dir) / "release"
        staged.mkdir()
        with tempfile.TemporaryDirectory(prefix="european-seen-") as temporary:
            db = sqlite3.connect(str(Path(temporary) / "record_ids.sqlite"))
            try:
                db.execute("CREATE TABLE seen (record_id TEXT PRIMARY KEY)")
                for path in paths:
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SHARD:
                        raise ContractError("unsafe or oversized evidence shard")
                    digest = sha256_file(path)
                    if path.stem != digest:
                        raise ContractError("immutable shard filename must equal SHA-256: " + path.name)
                    counts = {lang: _counters() for lang in sorted(PROFILES)}
                    with tempfile.TemporaryDirectory(prefix="european-shard-") as scratch:
                        files = {s: (Path(scratch) / (s + ".jsonl")).open("wb") for s in STATUSES}
                        try:
                            with path.open("rb") as handle:
                                for number, raw in enumerate(handle, 1):
                                    if number > 500000 or len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                                        raise ContractError("unbounded/malformed JSONL at line " + str(number))
                                    try:
                                        record = loads_unique(raw.decode("utf-8"))
                                    except UnicodeError as exc:
                                        raise ContractError("invalid UTF-8 at line " + str(number)) from exc
                                    row = validate_record(record, allowed_sources)
                                    try:
                                        db.execute("INSERT INTO seen VALUES (?)", (row["record_id"],))
                                    except sqlite3.IntegrityError as exc:
                                        raise ContractError("repeated record identity across shards") from exc
                                    counts[row["language_code"]][row["evidence_status"]] += 1
                                    files[row["evidence_status"]].write(_json_bytes(row))
                        finally:
                            for stream in files.values():
                                stream.close()
                        for status in STATUSES:
                            draft = Path(scratch) / (status + ".jsonl")
                            if draft.stat().st_size:
                                with draft.open("rb") as stream:
                                    target = staged / (digest + "." + status + ".jsonl")
                                    # Shards are capped at 64 MiB. Output is deterministic.
                                    _atomic_write(target, stream.read())
                    shard_total = sum(sum(c.values()) for c in counts.values())
                    report["total"] += shard_total
                    for lang in counts:
                        for status in STATUSES:
                            report["languages"][lang][status] += counts[lang][status]
                    report["shards"].append({"sha256": digest, "records": shard_total,
                                             "languages": {k: v for k, v in counts.items()
                                                           if sum(v.values())}})
            finally:
                db.close()
        report["status"] = "EVIDENCE_CLASSIFIED_NO_AUTO_RELEASE"
        _atomic_write(staged / "summary.json", _json_bytes(report))
        os.replace(staged, output_dir)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--shards-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = process_shards(args.repo_root, args.shards_dir, args.output_dir)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, KeyError) as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
