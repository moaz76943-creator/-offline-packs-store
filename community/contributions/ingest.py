#!/usr/bin/env python3
"""Bounded community intake. STAGED is never a publication or rights approval.

Validates, quarantines and stages approved multilingual lexical and translation submissions.
"""
import argparse
import fcntl
import gzip
import hashlib
import io
from itertools import islice
import json
import os
import re
import stat
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

MAX_INPUT = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
MAX_MEMBERS = 128
HASH = re.compile(r"^[0-9a-f]{64}$")


def unique_json(raw):
    def unique_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs)


def members(data, name):
    """Yield only flat .json members, capped before allocating expanded data."""
    total = 0
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError("invalid archive member count")
            seen = set()
            for info in infos:
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode):
                    raise ValueError("archive links/directories forbidden")
                part = info.filename
                if part in seen or part != Path(part).name or not part.endswith(".json") or "\\" in part or part.startswith("."):
                    raise ValueError("unsafe archive member")
                seen.add(part)
                total += info.file_size
                if info.file_size > MAX_EXPANDED or total > MAX_EXPANDED:
                    raise ValueError("archive expansion limit")
                with archive.open(info) as stream:
                    content = stream.read(info.file_size + 1)
                if len(content) != info.file_size:
                    raise ValueError("archive size mismatch")
                yield part, content
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            infos = list(islice(archive, MAX_MEMBERS + 1))
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError("invalid archive member count")
            seen = set()
            for info in infos:
                part = info.name
                if not info.isfile() or part in seen or part != Path(part).name or not part.endswith(".json") or "\\" in part or part.startswith("."):
                    raise ValueError("unsafe tar member")
                seen.add(part)
                total += info.size
                if info.size > MAX_EXPANDED or total > MAX_EXPANDED:
                    raise ValueError("tar expansion limit")
                stream = archive.extractfile(info)
                if stream is None:
                    raise ValueError("missing archive member")
                with stream:
                    content = stream.read(info.size + 1)
                if len(content) != info.size:
                    raise ValueError("archive size mismatch")
                yield part, content
    elif name.endswith(".json.gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            raw = stream.read(MAX_EXPANDED + 1)
        if len(raw) > MAX_EXPANDED:
            raise ValueError("gzip expansion limit")
        yield name[:-3], raw
    elif name.endswith(".json"):
        yield name, data
    else:
        raise ValueError("unsupported format; use JSON or bounded JSON archive")


def validate_document(doc, valid_languages, validate_lexical, license_ids):
    validate_lexical(doc, publication=False)
    if not any(doc.get(k) for k in ("lexemes", "senses", "translations", "examples", "relations")):
        raise ValueError("empty lexical contribution")
    sources = []
    for collection in ("lexemes", "senses", "translations", "examples", "relations"):
        for record in doc[collection]:
            language = record.get("language")
            if language and language not in valid_languages:
                raise ValueError("unregistered language")

    def traverse(value):
        if isinstance(value, list):
            for child in value:
                traverse(child)
        elif isinstance(value, dict):
            if "source" in value:
                source = value["source"]
                if (not isinstance(source, dict) or source.get("license_id") not in license_ids or
                    source.get("fixture_only") is not False or not source.get("source_id") or
                    not source.get("dataset_version") or not source.get("record_locator") or
                    not source.get("publisher") or not source.get("origin_url") or
                    not isinstance(source.get("artifact_sha256"), str) or
                    not HASH.fullmatch(source["artifact_sha256"])):
                    raise ValueError("missing/fixture/unverified source provenance")
                sources.append({k: source[k] for k in ("source_id", "dataset_version", "record_locator", "license_id", "artifact_sha256")})
            for child in value.values():
                traverse(child)
    traverse(doc)
    return sources


@contextmanager
def locked(root):
    fd = os.open(root / ".intake.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def save_atomic(path, content):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".intake-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ingest(source, staging_root, *, registry_path=None, validator=None, licenses=None):
    """Operator-supplied overrides are for isolated tests; never evidence of rights."""
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError("symlink or missing submission")
    if source.stat().st_size > MAX_INPUT:
        raise ValueError("input exceeds size limit")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size > MAX_INPUT or not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("unsafe or oversized submission")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(MAX_INPUT + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_INPUT:
        raise ValueError("input exceeds size limit")
    if registry_path is None:
        registry_path = Path(__file__).resolve().parents[2] / "catalog/content_readiness.v1.json"
    registry = unique_json(Path(registry_path).read_bytes())
    valid_languages = set(registry["states"])
    if validator is None:
        from standards.lexical.validate import validate as validator
    if licenses is None:
        from legal.ledger.admission import LICENSES as licenses
    seen_ids = set()
    seen_entry_ids = set()
    record_sources = []
    count = 0
    for name, raw in members(data, source.name):
        doc = unique_json(raw)
        # Establish record types and canonical IDs before indexing any of them.
        document_sources = validate_document(doc, valid_languages, validator, licenses)
        if doc["document_id"] in seen_ids:
            raise ValueError("duplicate document ID")
        seen_ids.add(doc["document_id"])
        for collection, key in (('lexemes', 'lexeme_id'), ('senses', 'sense_id'),
                                ('translations', 'translation_id'), ('examples', 'example_id'),
                                ('relations', 'relation_id')):
            for record in doc.get(collection, []):
                if key in record:
                    rid = record[key]
                    if rid in seen_entry_ids:
                        raise ValueError(f"duplicate entry ID: {rid}")
                    seen_entry_ids.add(rid)
        record_sources.extend(document_sources)
        count += 1
    if not count:
        raise ValueError("empty submission")
    digest = hashlib.sha256(data).hexdigest()
    root = Path(staging_root)
    if root.is_symlink():
        raise ValueError("symlink staging root")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    staged, records = root / "staged", root / "records"
    for directory in (staged, records):
        if directory.is_symlink():
            raise ValueError("symlink staging subdirectory")
        directory.mkdir(exist_ok=True)
    receipt = {"sha256": digest, "state": "STAGED_REVIEW_REQUIRED", "file": digest + ".bin",
               "documents": count, "claimed_sources": sorted(record_sources, key=lambda x: json.dumps(x, sort_keys=True)),
               "rights_approved": False}
    with locked(root):
        path = staged / (digest + ".bin")
        index = records / (digest + ".json")
        if path.is_symlink() or index.is_symlink():
            raise ValueError("symlink staged file")
        # A surviving receipt is evidence too: validate it even if the data
        # write is missing. Never overwrite a contradictory transaction index.
        if index.exists():
            if (not index.is_file() or index.stat().st_size > MAX_EXPANDED
                    or unique_json(index.read_bytes()) != receipt):
                raise ValueError("staging index mismatch")
        if path.exists():
            if not path.is_file() or path.stat().st_size > MAX_INPUT:
                raise ValueError("staging collision")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("staging collision")
            if index.is_file():
                return receipt
        if not path.exists():
            save_atomic(path, data)
        if not index.exists():
            save_atomic(index, json.dumps(receipt, sort_keys=True, ensure_ascii=False).encode())
    return receipt



def quarantine_submission(source, staging_root, reason):
    """Retain bounded rejected input with an explicit non-approval receipt."""
    root = Path(staging_root)
    if root.is_symlink():
        raise ValueError("unsafe quarantine root")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_INPUT:
            raise ValueError("unsafe quarantine input")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            data = stream.read(MAX_INPUT + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_INPUT:
        raise ValueError("unsafe quarantine size")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    rejected = root / "quarantined"
    if rejected.is_symlink():
        raise ValueError("unsafe quarantine directory")
    rejected.mkdir(exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    receipt = {"sha256": digest, "state": "QUARANTINED", "rights_approved": False,
               "reason": str(reason)[:200]}
    with locked(root):
        original = rejected / (digest + ".bin")
        receipt_path = rejected / (digest + ".json")
        if original.is_symlink() or receipt_path.is_symlink():
            raise ValueError("unsafe quarantine entry")
        if not original.exists():
            save_atomic(original, data)
        elif hashlib.sha256(original.read_bytes()).hexdigest() != digest:
            raise ValueError("quarantine content collision")
        if not receipt_path.exists():
            save_atomic(receipt_path, json.dumps(receipt, sort_keys=True).encode("utf-8"))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path)
    parser.add_argument("--staging-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(ingest(args.submission, args.staging_root), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError, EOFError) as exc:
        try:
            quarantine_submission(args.submission, args.staging_root, str(exc))
        except (OSError, ValueError):
            pass
        print("REJECTED:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
