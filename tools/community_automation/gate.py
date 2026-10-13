#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
"""Community automation gate for dictionary, grammar, and compact semantic assets."""
import argparse
import sys
import os
import hashlib
import json
import zipfile
import tarfile
import io
import re
import stat
from pathlib import Path
from itertools import islice

# Re-use existing configuration and methods where possible
from community.contributions.ingest import (
    MAX_INPUT, MAX_EXPANDED, MAX_MEMBERS,
    unique_json, locked, save_atomic, validate_document
)

# Load dependencies for document validation
from standards.lexical.validate import validate as validate_lexical
from legal.ledger.admission import LICENSES

HASH = re.compile(r"^[0-9a-f]{64}$")

def check_workspace(staging_root):
    root = Path(staging_root)
    if not root.exists():
         root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    if root.is_symlink():
         raise ValueError("symlink staging root")
    if not os.access(root, os.W_OK):
         raise ValueError("workspace access is not authorized")
    return root

def quarantine_submission(source, staging_root, reason):
    """Retain bounded rejected input with an explicit non-approval receipt."""
    root = check_workspace(staging_root)
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

def members_all(data, name):
    """Yield all supported members (.json, .jsonl, .svg, .vct), capped."""
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
                # Disallow path traversal directly
                if part in seen or part != Path(part).name or "\\" in part or part.startswith("."):
                    raise ValueError("unsafe archive member")
                if not part.endswith((".json", ".jsonl", ".svg", ".vct")):
                    raise ValueError("executable payloads or unsupported files rejected")
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
                if not info.isfile() or part in seen or part != Path(part).name or "\\" in part or part.startswith("."):
                    raise ValueError("unsafe tar member")
                if not part.endswith((".json", ".jsonl", ".svg", ".vct")):
                    raise ValueError("executable payloads or unsupported files rejected")
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
    else:
        raise ValueError("unsupported format; use bounded zip or tar archive")

def validate_svg(content):
    if b"<script" in content or b"<!ENTITY" in content or b"xlink:href=" in content:
        raise ValueError("unsafe media: SVG contains script, entity, or external reference")
    # basic sanity check for SVG tag
    if b"<svg" not in content:
         raise ValueError("unsafe media: SVG file lacking svg tag")

def validate_vct(content):
    if len(content) > 2048:
        raise ValueError("compact vector size limit exceeded")
    import zlib
    try:
        zlib.decompress(content)
    except Exception:
         raise ValueError("invalid compact vector: failed to decompress")

def ingest(source, staging_root, registry_path=None):
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

    root = check_workspace(staging_root)

    if registry_path is None:
        registry_path = Path(__file__).resolve().parents[2] / "catalog/content_readiness.v1.json"
    registry = unique_json(Path(registry_path).read_bytes())
    valid_languages = set(registry["states"])

    seen_ids = set()
    record_sources = []
    count = 0

    has_valid_media = False

    for name, raw in members_all(data, source.name):
        if name.endswith(".json") or name.endswith(".jsonl"):
            doc = unique_json(raw)
            if doc.get("document_id") in seen_ids:
                raise ValueError("duplicate document ID")
            if "document_id" in doc:
                seen_ids.add(doc["document_id"])
            record_sources.extend(validate_document(doc, valid_languages, validate_lexical, LICENSES))
            count += 1
        elif name.endswith(".svg"):
            validate_svg(raw)
            has_valid_media = True
            count += 1
        elif name.endswith(".vct"):
            validate_vct(raw)
            has_valid_media = True
            count += 1

    if not count:
        raise ValueError("empty submission")

    digest = hashlib.sha256(data).hexdigest()

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
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest or not index.is_file():
                raise ValueError("staging collision or interrupted transaction")
            if unique_json(index.read_bytes()) != receipt:
                raise ValueError("staging index mismatch")
            return receipt
        save_atomic(path, data)
        save_atomic(index, json.dumps(receipt, sort_keys=True, ensure_ascii=False).encode())
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
