#!/usr/bin/env python3
"""Deterministic bounded export from verified review handoffs and rights ledger.

Exporting creates local files only; it never publishes a corpus. Human legal
review remains mandatory, irrespective of a green automated check.
"""
import argparse
import fcntl
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from community.review.state_machine import ReviewStateMachine, canonical, existing_file, safe_directory, safe_name

HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_FILES = 128
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
# ZIP_STORED output may add member headers and bounded attribution metadata.
MAX_RELEASE_BYTES = MAX_TOTAL + 2 * 1024 * 1024
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class ExportError(ValueError):
    pass


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(65536), b""):
            h.update(part)
    return h.hexdigest()


def read_json(path, maximum=1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ExportError("missing, symlinked, or oversized manifest")
    with path.open("rb") as f:
        return json.loads(f.read(maximum + 1).decode("utf-8"))


def safe_file(root, filename):
    if not isinstance(filename, str) or filename != Path(filename).name or "\\" in filename or filename.startswith("."):
        raise ExportError("unsafe input filename")
    return existing_file(Path(root) / filename, root)


def zip_entry(archive, name, content):
    info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o644 << 16
    archive.writestr(info, content)



def _audit_member(source, destination=None, item_type="lexical"):
    """Bounded read and shared semantic audit for new AND cached releases."""
    h = hashlib.sha256()
    total = 0
    if item_type == "semantic":
        data = b""
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > 2048:
                raise ExportError("file changed during packaging or too large")
            h.update(chunk)
            data += chunk
            if destination is not None:
                destination.write(chunk)
        from tools.visual_lexicon.core import decode_token
        try:
            decode_token(data)
        except Exception as exc:
            raise ExportError("invalid semantic token") from exc
        return total, h.hexdigest()

    lexemes = {}
    senses = {}
    translations = []
    seen_lexemes = set()
    seen_senses = set()
    while True:
        # A changed source can grow after _prepare; never iterate unbounded lines.
        line = source.readline(MAX_FILE + 1)
        if not line:
            break
        total += len(line)
        if total > MAX_FILE:
            raise ExportError("file changed during packaging or too large")
        h.update(line)
        if destination is not None:
            destination.write(line)
        if not line.strip().startswith(b"{"):
            continue
        try:
            obj = json.loads(line.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ExportError("invalid unicode in stream") from exc
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        for lexeme in obj.get("lexemes", []):
            if not isinstance(lexeme, dict):
                raise ExportError("invalid lexeme record")
            lex_id = lexeme.get("lexeme_id")
            if isinstance(lex_id, str) and lex_id:
                if lex_id in seen_lexemes:
                    raise ExportError("duplicate lexeme_id found in stream")
                seen_lexemes.add(lex_id)
                lexemes[lex_id] = lexeme.get("language")
            for sense in lexeme.get("senses", []):
                if not isinstance(sense, dict):
                    raise ExportError("invalid nested sense record")
                sid = sense.get("sense_id")
                if isinstance(sid, str) and sid:
                    if sid in seen_senses:
                        raise ExportError("duplicate sense_id found in stream")
                    seen_senses.add(sid)
                    senses[sid] = lex_id
        for sense in obj.get("senses", []):
            if not isinstance(sense, dict):
                raise ExportError("invalid sense record")
            sid = sense.get("sense_id")
            if isinstance(sid, str) and sid:
                if sid in seen_senses:
                    raise ExportError("duplicate sense_id found in stream")
                seen_senses.add(sid)
                senses[sid] = sense.get("lexeme_id")
        for tr in obj.get("translations", []):
            if not isinstance(tr, dict):
                raise ExportError("invalid translation record")
            if all(k in tr for k in ("from_sense_id", "to_sense_id", "language")):
                translations.append((tr["from_sense_id"], tr["to_sense_id"], tr["language"]))
    for from_id, to_id, target_lang in translations:
        # Stable IDs are opaque. Direction is given by sense -> lexeme -> language.
        if not isinstance(from_id, str) or not isinstance(to_id, str):
            raise ExportError("reversed translation pair detected")
        from_lang = lexemes.get(senses.get(from_id))
        to_lang = lexemes.get(senses.get(to_id))
        if (not isinstance(from_lang, str) or not isinstance(to_lang, str)
                or from_lang == to_lang or target_lang != to_lang):
            raise ExportError("reversed translation pair detected")
    return total, h.hexdigest()



class CommunityExporter:
    def __init__(self, source_dir, output_dir, review_machine, *, language=None, categories=None, repository_root=None):
        if Path(source_dir).is_symlink():
            raise ExportError("symlink source root")
        self.source = Path(source_dir).resolve()
        self.output = Path(output_dir)
        self.review = review_machine
        self.language = language
        self.categories = set(categories) if categories else None
        self.repo = Path(repository_root or Path(__file__).resolve().parents[2]).resolve()

        # Verify repository access and required source contracts
        if not self.repo.is_dir() or not (self.repo / "catalog").exists() or not (self.repo / "legal").exists():
            raise ExportError("BLOCKED_REPOSITORY_ACCESS")

    def _admitted(self):
        """Use the existing authoritative independent source-rights gate."""
        from legal.ledger.admission import evaluate
        ledger = read_json(self.repo / "legal/ledger/sources.json")
        errors = evaluate(ledger, {"languages": [], "packs": []}, [], self.repo)
        if errors:
            raise ExportError("rights ledger blocked: " + "; ".join(errors[:3]))
        return {s["source_id"]: s for s in ledger["sources"]}

    def _prepare(self):
        manifest = read_json(self.source / "manifest.json")
        items = manifest.get("items")
        if not isinstance(items, list) or not items or len(items) > MAX_FILES:
            raise ExportError("empty or oversized export manifest")
        ledger = self._admitted()
        registry = read_json(self.repo / "catalog/content_readiness.v1.json")
        if registry.get("schema_version") != "1.0.0" or not isinstance(registry.get("states"), dict):
            raise ExportError("untrusted language registry")
        languages = set(registry["states"])
        entries, notices, seen, total = [], [], set(), 0
        for item in items:
            if not isinstance(item, dict):
                raise ExportError("invalid export entry")

            if self.categories and item.get("type") not in self.categories:
                continue

            aid = safe_name(item.get("id"))
            if aid in seen:
                raise ExportError("duplicate export identity")
            seen.add(aid)
            if item.get("type") not in ("lexical", "sentences", "grammar", "semantic"):
                raise ExportError("disallowed artifact type")
            digest = item.get("sha256")
            if not isinstance(digest, str) or not HASH.fullmatch(digest):
                raise ExportError("missing expected content SHA-256")
            path = safe_file(self.source, item.get("filename"))
            size = path.stat().st_size
            total += size
            if size > MAX_FILE or total > MAX_TOTAL:
                raise ExportError("export byte limit exceeded")
            if file_hash(path) != digest:
                raise ExportError("mismatched content SHA-256")
            handoff = self.review.verify_handoff(safe_name(item.get("submission_id")))
            if handoff["content_hash"] != digest or handoff["artifact"] != item["filename"]:
                raise ExportError("handoff refers to different content")
            meta = handoff["metadata"]
            if self.language and meta.get("language") != self.language:
                continue

            if meta["language"] not in languages:
                raise ExportError("unregistered language in review handoff")
            if (meta["source_id"] != item.get("source_id") or meta["license_id"] != item.get("license") or
                meta["dataset_version"] != item.get("source_version")):
                raise ExportError("contradictory source or licensing metadata")
            source = ledger.get(meta["source_id"])
            if not source or source.get("status") != "APPROVED_FOR_REDISTRIBUTION":
                raise ExportError("source not approved by rights ledger")
            if (source.get("retrieval", {}).get("sha256") != meta["source_artifact_sha256"] or
                source.get("dataset_version") != meta["dataset_version"] or
                source.get("publisher") != meta["publisher"] or
                source.get("origin_url") != meta["origin_url"] or
                source.get("license", {}).get("id") != meta["license_id"]):
                raise ExportError("ledger provenance mismatch")
            if meta["license_id"] not in ("CC0-1.0", "PUBLIC-DOMAIN"):
                raise ExportError("license obligations not implemented for this export format")
            expected_kind = {"lexical": "dictionary", "sentences": "examples",
                             "grammar": "morphology", "semantic": "vector_art"}[item["type"]]
            if source.get("kind") != expected_kind:
                raise ExportError("source kind does not match export category")
            entries.append((aid, path, digest, item["type"], meta["language"]))
            notices.append({"id": aid, "source_id": meta["source_id"], "publisher": meta["publisher"],
                            "origin_url": meta["origin_url"], "dataset_version": meta["dataset_version"],
                            "license_id": meta["license_id"], "license_evidence_url": source["license"]["evidence_url"],
                            "record_locator": meta["record_locator"], "sha256": digest})
        if len(canonical(notices)) > 65536:
            raise ExportError("attribution metadata exceeds bounded export size")
        return sorted(entries), sorted(notices, key=lambda x: x["id"])

    def run(self):
        entries, notices = self._prepare()
        if self.output.is_symlink():
            raise ExportError("symlink output directory")
        target = safe_directory(self.output)
        releases = safe_directory(target / "releases")
        lock_fd = os.open(target / ".export.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            digest = hashlib.sha256(canonical({"files": [(a, d) for a, _, d, _, _ in entries], "notices": notices})).hexdigest()
            release = releases / (digest + ".zip")
            if release.is_symlink():
                raise ExportError("symlink release target")
            if not release.exists():
                fd, tmp = tempfile.mkstemp(dir=releases, prefix=".export-")
                try:
                    with os.fdopen(fd, "wb") as stream:
                        with zipfile.ZipFile(stream, "w", allowZip64=False) as archive:
                            for aid, path, expected, item_type, lang in entries:
                                ext = ".vct" if item_type == "semantic" else ".bin"
                                info = zipfile.ZipInfo("data/" + aid + ext, date_time=ZIP_DATE)
                                info.compress_type = zipfile.ZIP_STORED
                                info.external_attr = 0o644 << 16
                                with path.open("rb") as source, archive.open(info, "w", force_zip64=False) as dest:
                                    size_written, actual_hash = _audit_member(source, dest, item_type=item_type)
                                if actual_hash != expected:
                                    raise ExportError("file changed during packaging")
                            zip_entry(archive, "ATTRIBUTION.json", canonical(notices))
                        stream.flush()
                        os.fsync(stream.fileno())
                    if os.path.getsize(tmp) > MAX_RELEASE_BYTES:
                        raise ExportError("generated export exceeds archive byte limit")
                    os.replace(tmp, release)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            else:
                # ZIP metadata is decoded before member-level checks; cap the
                # entire untrusted cached file before opening ZipFile.
                if not release.is_file() or release.stat().st_size > MAX_RELEASE_BYTES:
                    raise ExportError("untrusted cached export exceeds archive byte limit")
                with zipfile.ZipFile(release) as archive:
                    expected_names = ["data/" + aid + (".vct" if t == "semantic" else ".bin") for aid, _, _, t, _ in entries] + ["ATTRIBUTION.json"]
                    if archive.namelist() != expected_names:
                        raise ExportError("corrupt cached export")
                    for info in archive.infolist():
                        if info.compress_type != zipfile.ZIP_STORED or info.file_size > MAX_FILE:
                            raise ExportError("untrusted cached archive member")
                    for aid, path, expected, item_type, lang in entries:
                        ext = ".vct" if item_type == "semantic" else ".bin"
                        with archive.open("data/" + aid + ext) as stream:
                            size, actual_hash = _audit_member(stream, item_type=item_type)
                        if size > MAX_FILE or actual_hash != expected:
                            raise ExportError("cached archive content mismatch")
                    with archive.open("ATTRIBUTION.json") as stream:
                        attribution = stream.read(65537)
                    if len(attribution) > 65536 or attribution != canonical(notices):
                        raise ExportError("cached attribution mismatch")
            sha = file_hash(release)
            receipt = {"release": release.name, "sha256": sha, "items": len(entries), "published": False}
            fd, tmp = tempfile.mkstemp(dir=target, prefix=".pointer-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical(receipt))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, target / "CURRENT.json")
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return receipt
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--language", help="Filter by language ID")
    parser.add_argument("--categories", help="Comma-separated list of categories to export")
    parser.add_argument("--operator-keys", required=True, help="Protected JSON file outside submissions/repository")
    args = parser.parse_args(argv)
    try:
        keys_path = Path(args.operator_keys)
        if keys_path.is_symlink() or not keys_path.is_file() or keys_path.stat().st_mode & 0o077:
            raise ExportError("operator authority file must be regular and mode 0600")
        restricted = (Path(__file__).resolve().parents[2], Path(args.source),
                      Path(args.review_root), Path(args.output))
        if any(keys_path.resolve().is_relative_to(p.resolve()) for p in restricted):
            raise ExportError("operator authority keys must be outside repository and corpus")
        keys = read_json(keys_path, 16384)
        import base64
        validator = {k: base64.b64decode(v, validate=True) for k, v in keys["validators"].items()}
        reviewers = {k: base64.b64decode(v, validate=True) for k, v in keys["reviewers"].items()}
        machine = ReviewStateMachine(args.review_root, args.source, validator_keys=validator, reviewer_keys=reviewers)
        cats = args.categories.split(",") if args.categories else None
        result = CommunityExporter(args.source, args.output, machine, language=args.language, categories=cats).run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, PermissionError, zipfile.BadZipFile) as exc:
        print("BLOCKED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
