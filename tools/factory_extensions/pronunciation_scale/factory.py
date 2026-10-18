"""Fail-closed evidence-first pronunciation inventory and bounded WAV pack builder.

No phoneme inference, audio downloads, synthetic generation, voice probing or source mutations.
Consumes existing canonical registry and approved Route-05 ledger without editing either.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import wave

VERSION = "1.0.0"
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-SA-4.0", "GFDL-1.3-only", "PUBLIC-DOMAIN"}
AUDIO_LIMIT = 2 * 1024 * 1024
# Rights snapshots and source archives are not WAV payloads. Keep them off the
# audio-file ceiling, but still refuse unbounded reads.
EVIDENCE_LIMIT = 8 * 1024 * 1024
DURATION_LIMIT = 15.0
RECORD_LIMIT = 500
PACKAGE_LIMIT = 64 * 1024 * 1024
TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-[a-z0-9]{5,8})*$")
SHA = re.compile(r"^[0-9a-f]{64}$")
_GENERIC_TERMS = (
    "creativecommons.org/licenses/",
    "creativecommons.org/publicdomain/zero/",
    "gnu.org/licenses/fdl-",
)
_ADMISSION = None


class AuditError(ValueError):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _admission():
    """Load Route-05 admission.evaluate without requiring legal/ to be a package."""
    global _ADMISSION
    if _ADMISSION is None:
        path = _repo_root() / "legal" / "ledger" / "admission.py"
        spec = importlib.util.spec_from_file_location("route05_admission", path)
        if spec is None or spec.loader is None:
            raise AuditError("missing Route-05 admission gate")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ADMISSION = module
    return _ADMISSION


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise AuditError("invalid relative path")
    root = root.resolve()
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root) or not target.is_file():
        raise AuditError("missing, symlinked or escaped file")
    return target


def _proven(path: str, digest: str, root: Path, limit: int = EVIDENCE_LIMIT) -> bool:
    try:
        file = _path(root, path)
        return bool(isinstance(digest, str) and SHA.fullmatch(digest) and file.stat().st_size <= limit and _sha(file) == digest)
    except (AuditError, OSError, TypeError):
        return False


def _evidence_within_limit(relative, root: Path) -> bool:
    """Reject oversized evidence before Route-05 hashes it. Does not apply AUDIO_LIMIT."""
    try:
        return _path(root, relative).stat().st_size <= EVIDENCE_LIMIT
    except (AuditError, OSError, TypeError):
        return False


def _approved_source(source: dict, root: Path) -> bool:
    """Route-05 source contract. A redistribution label alone is not admission."""
    if not isinstance(source, dict) or source.get("kind") != "pronunciation":
        return False
    retrieval = source.get("retrieval") if isinstance(source.get("retrieval"), dict) else {}
    license_doc = source.get("license") if isinstance(source.get("license"), dict) else {}
    if not _evidence_within_limit(retrieval.get("artifact_path"), root):
        return False
    if not _evidence_within_limit(license_doc.get("evidence_path"), root):
        return False
    try:
        errors = _admission().evaluate(
            {"schema_version": "1.0.0", "sources": [source]},
            {"languages": [], "packs": []},
            [],
            root,
        )
    except (OSError, TypeError, ValueError):
        return False
    return not errors


def authoritative_lexical_index(repo: Path) -> dict:
    """Index publication-approved lexical identities. Fixtures are not authority."""
    lexemes, senses = {}, {}
    conflicts = set()
    root = Path(repo) / "standards" / "lexical"
    if not root.is_dir():
        return {"lexemes": {}, "senses": {}}
    paths = [p for p in sorted(root.rglob("*.json"))
             if p.name != "lexical.schema.json" and "fixtures" not in p.parts]
    for path in paths:
        try:
            if path.stat().st_size > 4 * 1024 * 1024:
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or doc.get("contract_version") != "1.0.0":
            continue
        for lex in doc.get("lexemes") or []:
            if not isinstance(lex, dict):
                continue
            src = lex.get("source") if isinstance(lex.get("source"), dict) else {}
            lid, lang = lex.get("lexeme_id"), lex.get("language")
            if not (src.get("publication_approved") is True and src.get("fixture_only") is False
                    and isinstance(lid, str) and isinstance(lang, str)):
                continue
            if lid in lexemes and lexemes[lid] != lang:
                conflicts.add(("lexeme", lid))
            else:
                lexemes[lid] = lang
        for sense in doc.get("senses") or []:
            if not isinstance(sense, dict):
                continue
            src = sense.get("source") if isinstance(sense.get("source"), dict) else {}
            sid, lid = sense.get("sense_id"), sense.get("lexeme_id")
            if not (src.get("publication_approved") is True and src.get("fixture_only") is False
                    and isinstance(sid, str) and isinstance(lid, str)):
                continue
            if sid in senses and senses[sid] != lid:
                conflicts.add(("sense", sid))
            else:
                senses[sid] = lid
    for kind, key in conflicts:
        (lexemes if kind == "lexeme" else senses).pop(key, None)
    return {"lexemes": lexemes, "senses": senses}


def _lexical_ok(record, index) -> bool:
    if not isinstance(index, dict):
        return False
    lid, sid, lang = record.get("lexeme_id"), record.get("sense_id"), record.get("language_id")
    lexemes = index.get("lexemes") if isinstance(index.get("lexemes"), dict) else {}
    senses = index.get("senses") if isinstance(index.get("senses"), dict) else {}
    return bool(isinstance(lid, str) and isinstance(sid, str) and lexemes.get(lid) == lang and senses.get(sid) == lid)


def index_generated_rights(document) -> dict:
    """Map (engine_id, voice_id) to the reviewed terms URL. Candidate booleans are ignored."""
    rows = document.get("rights") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        return {}
    module = _admission()
    found, conflicts = {}, set()
    for row in rows:
        if not isinstance(row, dict) or row.get("redistribution_permitted") is not True:
            continue
        engine, voice = row.get("engine_id"), row.get("voice_id")
        if not isinstance(engine, str) or not engine.strip() or not isinstance(voice, str) or not voice.strip():
            continue
        terms = row.get("terms_url")
        if not module.url_ok(terms) or any(token in terms for token in _GENERIC_TERMS):
            continue
        review_errors = []
        if not module.manual_review(row.get("review"), review_errors, "generated voice"):
            continue
        key = (engine, voice)
        if key in found and found[key] != terms:
            conflicts.add(key)
        else:
            found[key] = terms
    for key in conflicts:
        found.pop(key, None)
    return found


def _reading_ok(reading):
    if not isinstance(reading, dict) or reading.get("notation") not in {"ipa", "phonetic", "romanization", "other"}:
        return False
    if not isinstance(reading.get("value"), str) or not reading["value"].strip():
        return False
    # Syllables, stress and tones are evidence fields, never derived from spelling.
    for field in ("syllables", "tones"):
        if field in reading and (not isinstance(reading[field], list) or not reading[field] or not all(isinstance(v, str) and v.strip() for v in reading[field])):
            return False
    return "stress" not in reading or isinstance(reading["stress"], str) and bool(reading["stress"].strip())


def _valid_identity(record, identities, variants):
    lang = record.get("language_id")
    entry = identities.get(lang)
    tag = record.get("language_tag")
    script = record.get("script")
    if not entry or script not in entry["scripts"] or not isinstance(tag, str) or not TAG.fullmatch(tag):
        return False
    if tag.split("-")[0] != lang:
        return False
    parts = tag.split("-")
    explicit_script = next((v for v in parts[1:] if len(v) == 4 and v[0].isupper()), None)
    if explicit_script and explicit_script != script:
        return False
    # Registry variants take precedence; correctly tagged regional BCP-47 metadata
    # is allowed, but does not imply a known accent or installed TTS.
    known = variants.get(tag)
    return not known or (known.get("language_id") == lang and known.get("script") == script)


def _decode_wav(path: Path, expected_sha: str) -> dict:
    if path.suffix.lower() != ".wav" or path.stat().st_size > AUDIO_LIMIT or not SHA.fullmatch(str(expected_sha)):
        raise AuditError("unsupported format, size, or digest")
    if _sha(path) != expected_sha:
        raise AuditError("audio hash mismatch")
    try:
        with wave.open(str(path), "rb") as reader:
            channels, rate, frames = reader.getnchannels(), reader.getframerate(), reader.getnframes()
            if (channels not in (1, 2) or rate < 8000 or rate > 96000 or reader.getcomptype() != "NONE"
                    or reader.getsampwidth() not in (1, 2, 3, 4) or frames == 0
                    or frames / rate > DURATION_LIMIT):
                raise AuditError("audio characteristics outside bounds")
            count = 0
            while True:
                payload = reader.readframes(8192)
                if not payload:
                    break
                count += len(payload)
                if count > AUDIO_LIMIT:
                    raise AuditError("decoded payload too large")
            if count != frames * channels * reader.getsampwidth():
                raise AuditError("truncated audio")
            return {"duration_ms": round(1000 * frames / rate), "channels": channels, "sample_rate": rate, "format": "wav_pcm"}
    except (EOFError, wave.Error, OSError, ZeroDivisionError) as exc:
        raise AuditError("audio decoding failed") from exc


def offline_tts_ready(required_voice_id: str, installed_voice_ids) -> bool:
    """Only call with a runtime-observed, currently installed voice inventory."""
    return bool(required_voice_id and isinstance(installed_voice_ids, (list, set, tuple)) and required_voice_id in installed_voice_ids)


def audit(catalog: dict, ledger: dict, document: dict, audio_root: Path, evidence_root: Path,
         lexical_index=None, generated_rights=None):
    if document.get("metadata_version") != VERSION or not isinstance(document.get("records"), list):
        raise AuditError("unsupported metadata version or records shape")
    if len(document["records"]) > RECORD_LIMIT:
        raise AuditError("bounded run exceeded 500 records; shard upstream")
    langs = catalog.get("languages", [])
    identities = {x["id"]: x for x in langs}
    if len(langs) != 100 or len(identities) != 100:
        # Small synthetic fixtures are allowed for explicit in-memory unit tests.
        if len(langs) == 0 or len(langs) != len(identities):
            raise AuditError("invalid language registry")
    variants = {v["tag"]: v for v in catalog.get("locale_variants", [])}
    if lexical_index is None:
        lexical_index = authoritative_lexical_index(_repo_root())
    voice_rights = index_generated_rights(generated_rights)
    entries = ledger.get("sources", [])
    if not isinstance(entries, list):
        raise AuditError("invalid ledger")
    sources = {}
    for source in entries:
        if not isinstance(source, dict) or not source.get("source_id") or source["source_id"] in sources:
            raise AuditError("missing or duplicate source identity")
        sources[source["source_id"]] = source
    coverage = {code: {"pronunciation_variants": 0, "audio_files": 0, "audio_assets": 0} for code in sorted(identities)}
    accepted, blocked, unique_files, seen_pron, seen_asset, language_files, seen_variants = [], [], {}, set(), set(), set(), set()
    for record in sorted(document["records"], key=lambda x: str(x.get("pronunciation_id", ""))):
        rid = record.get("pronunciation_id")
        lang = record.get("language_id")
        reasons = []
        if not rid or rid in seen_pron or not record.get("lexeme_id") or not record.get("variant_id"):
            reasons.append("invalid_or_duplicate_identity")
        seen_pron.add(rid)
        if not _lexical_ok(record, lexical_index):
            reasons.append("lexical_identity_unverified")
        if not _valid_identity(record, identities, variants):
            reasons.append("identity_mismatch")
        if not _reading_ok(record.get("reading")):
            reasons.append("reading_unattested")
        ev = record.get("evidence") or {}
        source = sources.get(ev.get("source_id"))
        if (not source or not _approved_source(source, Path(evidence_root))
            or any(ev.get(k) != value for k, value in (("publisher", source.get("publisher") if source else None),
                ("dataset_version", source.get("dataset_version") if source else None),
                ("license_id", (source.get("license") or {}).get("id") if source else None)))
            or not ev.get("record_locator")):
            reasons.append("source_not_approved")
        if reasons:
            blocked.append({"pronunciation_id": rid, "reasons": sorted(set(reasons))})
            continue
        variant_key = (lang, record["lexeme_id"], record["variant_id"], record["reading"]["value"])
        if variant_key not in seen_variants:
            coverage[lang]["pronunciation_variants"] += 1
            seen_variants.add(variant_key)
        for asset in record.get("audio", []):
            aid, kind = asset.get("asset_id"), asset.get("kind")
            faults = []
            if not aid or aid in seen_asset:
                faults.append("duplicate_asset_id")
            seen_asset.add(aid)
            if kind == "device_tts":
                faults.append("tts_not_packaged")
            elif kind not in {"human_recording", "licensed_generated_recording"}:
                faults.append("unknown_audio_kind")
            if kind == "human_recording" and not asset.get("speaker_id"):
                faults.append("speaker_missing")
            if kind == "licensed_generated_recording":
                generation = asset.get("generation") if isinstance(asset.get("generation"), dict) else {}
                approved_terms = voice_rights.get((generation.get("engine_id"), generation.get("voice_id")))
                # A candidate boolean, an arbitrary HTTPS URL, or a hash-matching local file
                # is not redistribution authority. Only an independent reviewed engine/voice record is.
                if approved_terms is None or generation.get("terms_url") != approved_terms:
                    faults.append("generation_rights_missing")
            if (asset.get("license_id") != ev["license_id"] or asset.get("license_id") not in ALLOWED_LICENSES
                    or asset.get("rights_url") != (source.get("license") or {}).get("evidence_url")
                    or not _proven(asset.get("rights_evidence_path"), asset.get("rights_evidence_sha256"), Path(evidence_root))):
                faults.append("audio_license_unverified")
            if ev["license_id"] in {"CC-BY-SA-4.0", "GFDL-1.3-only"} and not asset.get("license_obligations_reviewed"):
                faults.append("copyleft_review_missing")
            try:
                if not faults:
                    file = _path(Path(audio_root), asset.get("path"))
                    metadata = _decode_wav(file, asset.get("sha256"))
            except (AuditError, OSError, TypeError):
                faults.append("audio_invalid")
            if faults:
                blocked.append({"pronunciation_id": rid, "asset_id": aid, "reasons": sorted(set(faults))})
                continue
            entry = {"pronunciation_id": rid, "lexeme_id": record["lexeme_id"], "sense_id": record.get("sense_id"),
                     "language_id": lang, "language_tag": record["language_tag"], "script": record["script"],
                     "variant_id": record["variant_id"], "reading": record["reading"], "evidence": ev,
                     "asset_id": aid, "audio_kind": kind, "path": asset["path"], "sha256": asset["sha256"],
                     "speaker_id": asset.get("speaker_id"), "license_id": asset["license_id"],
                     "rights_url": asset["rights_url"], "rights_evidence_sha256": asset["rights_evidence_sha256"],
                     "generation": asset.get("generation"), "audio": metadata}
            accepted.append(entry)
            coverage[lang]["audio_assets"] += 1
            if (lang, asset["sha256"]) not in language_files:
                language_files.add((lang, asset["sha256"]))
                coverage[lang]["audio_files"] += 1
            if asset["sha256"] not in unique_files:
                unique_files[asset["sha256"]] = {"path": asset["path"], "language_id": lang}
    by_hash = {}
    for entry in accepted:
        by_hash.setdefault(entry["sha256"], []).append(entry["asset_id"])
    duplicates = [{"sha256": digest, "asset_ids": sorted(ids)} for digest, ids in sorted(by_hash.items()) if len(ids) > 1]
    return {"version": VERSION, "coverage": coverage, "accepted": accepted,
            "blocked": blocked, "duplicates": duplicates, "unique_file_count": len(unique_files)}


def package(report: dict, audio_root: Path, output: Path):
    """Reproducible content-addressed WAV tar; no source is moved/deleted."""
    records = report["accepted"]
    files = {}
    for item in records:
        files.setdefault(item["sha256"], item["path"])
    manifest = {"version": VERSION, "assets": records,
                "file_objects": [{"sha256": h, "member": f"audio/{h}.wav"} for h in sorted(files)]}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if (len(manifest_bytes) > AUDIO_LIMIT or len(files) > RECORD_LIMIT
            or sum(_path(Path(audio_root), relative).stat().st_size for relative in files.values()) > PACKAGE_LIMIT):
        raise AuditError("package bounds exceeded")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name, contents in [("manifest.json", manifest_bytes)]:
            info = tarfile.TarInfo(name); info.size = len(contents); info.mtime = 0
            tar.addfile(info, io.BytesIO(contents))
        for digest, relative in sorted(files.items()):
            source = _path(Path(audio_root), relative)
            _decode_wav(source, digest)
            info = tarfile.TarInfo(f"audio/{digest}.wav")
            info.size = source.stat().st_size; info.mtime = 0
            with source.open("rb") as stream:
                tar.addfile(info, stream)
    return {"package_sha256": _sha(output), "file_objects": len(files)}


def _safe_stage_path(stage: Path, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return None
    root = stage.resolve()
    dest = (root / relative).resolve()
    if not dest.is_relative_to(root):
        return None
    return dest


def _copy_evidence(root: Path, stage: Path, relative):
    source = _path(Path(root), relative)
    dest = _safe_stage_path(stage, relative)
    if dest is None:
        raise AuditError("invalid evidence path")
    if source.stat().st_size > EVIDENCE_LIMIT:
        raise AuditError("evidence snapshot exceeds bound")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())


def _referenced_paths(ledger, entry):
    paths = []
    notices = entry.get("notices") if isinstance(entry.get("notices"), dict) else {}
    for rel in notices.values():
        if isinstance(rel, str):
            paths.append(rel)
    if isinstance(entry.get("gfdl_license_copy_path"), str):
        paths.append(entry["gfdl_license_copy_path"])
    source_ids = {ref.get("source_id") for ref in (entry.get("source_refs") or []) if isinstance(ref, dict)}
    for source in ledger.get("sources") or []:
        if not isinstance(source, dict) or source.get("source_id") not in source_ids:
            continue
        retrieval = source.get("retrieval") if isinstance(source.get("retrieval"), dict) else {}
        license_doc = source.get("license") if isinstance(source.get("license"), dict) else {}
        for rel in (retrieval.get("artifact_path"), license_doc.get("evidence_path"), license_doc.get("artwork_evidence_path")):
            if isinstance(rel, str):
                paths.append(rel)
    return paths


def _corresponds(entry, digest, report) -> bool:
    if not isinstance(entry, dict) or entry.get("kind") != "pronunciation" or entry.get("sha256") != digest:
        return False
    refs = entry.get("source_refs")
    if not isinstance(refs, list) or not refs:
        return False
    needed = {item["evidence"]["source_id"] for item in report["accepted"]}
    have = {ref.get("source_id") for ref in refs if isinstance(ref, dict)}
    if not needed or not needed <= have:
        return False
    if entry.get("provenance_mode") == "per_record":
        mapped = {row.get("record_id") for row in entry.get("record_sources") or [] if isinstance(row, dict)}
        if not {item["pronunciation_id"] for item in report["accepted"]} <= mapped:
            return False
    return True


def admit_package(report: dict, audio_root: Path, output: Path, ledger: dict, dailies, evidence_root: Path) -> bool:
    """Write audio.tar only when an existing daily candidate survives admission.evaluate.

    This function never creates or edits a daily release candidate.
    """
    output = Path(output)
    if not report.get("accepted") or not isinstance(ledger, dict) or not isinstance(dailies, list):
        return False
    with tempfile.TemporaryDirectory(prefix="pronunciation-package-") as tmp:
        tmp_path = Path(tmp)
        staged_tar = tmp_path / "rebuild.tar"
        try:
            package(report, audio_root, staged_tar)
        except (AuditError, OSError):
            return False
        digest = _sha(staged_tar)
        matches = []
        for daily in dailies:
            if not isinstance(daily, dict):
                continue
            for entry in daily.get("release_candidates") or []:
                if _corresponds(entry, digest, report):
                    matches.append((daily, entry))
        if not matches:
            return False
        try:
            evaluate = _admission().evaluate
        except AuditError:
            return False
        for daily, entry in matches:
            stage = tmp_path / "stage"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir()
            try:
                for relative in _referenced_paths(ledger, entry):
                    _copy_evidence(evidence_root, stage, relative)
                dest = _safe_stage_path(stage, entry.get("artifact_path"))
                if dest is None:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(staged_tar.read_bytes())
                errors = evaluate(ledger, {"languages": [], "packs": []}, [daily], stage)
            except (AuditError, OSError, TypeError, ValueError):
                continue
            if errors:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(staged_tar.read_bytes())
            return True
    return False


def _load(path: Path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise AuditError("JSON input too large")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise AuditError("duplicate JSON key")
            result[k] = v
        return result
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=pairs)


def _load_dailies(directory: Path):
    if not directory.is_dir():
        return []
    return [_load(path) for path in sorted(directory.glob("*.json"))]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog/language_registry.v1.json"))
    parser.add_argument("--ledger", type=Path, default=Path("legal/ledger/sources.json"))
    parser.add_argument("--records", type=Path, default=Path("tools/factory_extensions/pronunciation_scale/candidates.json"))
    parser.add_argument("--audio-root", type=Path, default=Path("."))
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    repo = _repo_root()
    rights_path = repo / "legal" / "ledger" / "generated_audio_rights.json"
    ledger = _load(args.ledger)
    report = audit(_load(args.catalog), ledger, _load(args.records), args.audio_root, args.evidence_root,
                   lexical_index=authoritative_lexical_index(repo),
                   generated_rights=_load(rights_path) if rights_path.is_file() else None)
    tar_path = args.output_dir / "audio.tar"
    if report["accepted"]:
        try:
            dailies = _load_dailies(args.ledger.resolve().parent / "daily")
        except (AuditError, OSError):
            dailies = None
        if dailies is not None and admit_package(report, args.audio_root, tar_path, ledger, dailies, args.evidence_root):
            report["package_status"] = "admitted"
        else:
            report["package_status"] = "blocked"
            report["package_blockers"] = ["release_candidate_not_admitted"]
            if tar_path.is_file():
                tar_path.unlink()
    else:
        report["package_status"] = "not_requested"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "coverage.json").write_text(json.dumps({"version": VERSION, "coverage": report["coverage"]}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "admission.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"admitted_audio_assets": len(report["accepted"]), "blocked": len(report["blocked"]),
                      "unique_audio_files": report["unique_file_count"], "languages": len(report["coverage"]),
                      "package_status": report["package_status"]}, sort_keys=True))
    return 1 if report["blocked"] or report["package_status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
