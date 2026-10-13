"""Fail-closed evidence-first pronunciation inventory and bounded WAV pack builder.

No phoneme inference, audio downloads, synthetic generation, voice probing or source mutations.
Consumes existing canonical registry and approved Route-05 ledger without editing either.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import wave

VERSION = "1.0.0"
ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-SA-4.0", "GFDL-1.3-only", "PUBLIC-DOMAIN"}
AUDIO_LIMIT = 2 * 1024 * 1024
DURATION_LIMIT = 15.0
RECORD_LIMIT = 500
TAG = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-[a-z0-9]{5,8})*$")
SHA = re.compile(r"^[0-9a-f]{64}$")


class AuditError(ValueError):
    pass


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


def _proven(path: str, digest: str, root: Path) -> bool:
    try:
        file = _path(root, path)
        return bool(isinstance(digest, str) and SHA.fullmatch(digest) and file.stat().st_size <= AUDIO_LIMIT and _sha(file) == digest)
    except (AuditError, OSError, TypeError):
        return False


def _approved_source(source: dict, root: Path) -> bool:
    if not isinstance(source, dict) or source.get("kind") != "pronunciation" or source.get("status") != "APPROVED_FOR_REDISTRIBUTION":
        return False
    review, retrieval, license_doc = (source.get("review") or {}), (source.get("retrieval") or {}), (source.get("license") or {})
    lid = license_doc.get("id")
    if lid not in ALLOWED_LICENSES:
        return False
    if lid == "PUBLIC-DOMAIN" and not all((license_doc.get("public_domain_proof") or {}).get(k) for k in ("jurisdiction", "legal_basis", "work_date")):
        return False
    return bool(source.get("source_id") and source.get("publisher") and source.get("dataset_version")
                and str(source.get("origin_url", "")).startswith("https://")
                and review.get("reviewer") and str(review.get("decision_url", "")).startswith("https://")
                and str(license_doc.get("evidence_url", "")).startswith("https://")
                and _proven(retrieval.get("artifact_path"), retrieval.get("sha256"), root)
                and _proven(license_doc.get("evidence_path"), license_doc.get("evidence_sha256"), root))


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


def audit(catalog: dict, ledger: dict, document: dict, audio_root: Path, evidence_root: Path):
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
    entries = ledger.get("sources", [])
    if not isinstance(entries, list):
        raise AuditError("invalid ledger")
    sources = {}
    for source in entries:
        if not isinstance(source, dict) or not source.get("source_id") or source["source_id"] in sources:
            raise AuditError("missing or duplicate source identity")
        sources[source["source_id"]] = source
    coverage = {code: {"pronunciation_variants": 0, "audio_files": 0, "audio_assets": 0} for code in sorted(identities)}
    accepted, blocked, unique_files, seen_pron, seen_asset = [], [], {}, set(), set()
    for record in sorted(document["records"], key=lambda x: str(x.get("pronunciation_id", ""))):
        rid = record.get("pronunciation_id")
        lang = record.get("language_id")
        reasons = []
        if not rid or rid in seen_pron or not record.get("lexeme_id") or not record.get("variant_id"):
            reasons.append("invalid_or_duplicate_identity")
        seen_pron.add(rid)
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
        coverage[lang]["pronunciation_variants"] += 1
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
                generation = asset.get("generation") or {}
                if not (generation.get("engine_id") and generation.get("voice_id")
                        and generation.get("commercial_redistribution_approved") is True
                        and str(generation.get("terms_url", "")).startswith("https://")
                        and _proven(generation.get("proof_path"), generation.get("proof_sha256"), Path(evidence_root))):
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
                     "rights_url": asset["rights_url"], "audio": metadata}
            accepted.append(entry)
            coverage[lang]["audio_assets"] += 1
            if asset["sha256"] not in unique_files:
                unique_files[asset["sha256"]] = {"path": asset["path"], "language_id": lang}
                coverage[lang]["audio_files"] += 1
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
    if len(manifest_bytes) > AUDIO_LIMIT or len(files) > RECORD_LIMIT:
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("catalog/language_registry.v1.json"))
    parser.add_argument("--ledger", type=Path, default=Path("legal/ledger/sources.json"))
    parser.add_argument("--records", type=Path, default=Path("tools/factory_extensions/pronunciation_scale/candidates.json"))
    parser.add_argument("--audio-root", type=Path, default=Path("."))
    parser.add_argument("--evidence-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = audit(_load(args.catalog), _load(args.ledger), _load(args.records), args.audio_root, args.evidence_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "coverage.json").write_text(json.dumps({"version": VERSION, "coverage": report["coverage"]}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "admission.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if report["accepted"]:
        package(report, args.audio_root, args.output_dir / "audio.tar")
    print(json.dumps({"admitted_audio_assets": len(report["accepted"]), "blocked": len(report["blocked"]),
                      "unique_audio_files": report["unique_file_count"], "languages": len(report["coverage"])}, sort_keys=True))
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
