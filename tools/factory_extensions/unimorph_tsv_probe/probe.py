"""Inspection-only, bounded UniMorph TSV shard syntax probe.

This does not confer redistribution rights, produce lexemes, or admit forms.
No network access, and no modification to Route 05/08/13 contracts.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
FEATURE = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,63}\Z")
LANGUAGE = re.compile(r"[a-z]{3}\Z")
MAX_LINE_BYTES = 65536
MAX_SHARD_ROWS = 10000
MAX_FILE_BYTES = 1_000_000_000
DISALLOWED = frozenset({"Cf", "Cc", "Cs"})


class ProbeError(ValueError):
    """Reject malformed or unauthenticated inspection inputs."""


def sha256_stream(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_text(value: str) -> bool:
    return bool(value) and not any(unicodedata.category(ch) in DISALLOWED for ch in value)


def _bounded_lines(stream):
    """Yield physical lines without materializing an oversized line in memory."""
    while True:
        raw = stream.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n") and len(raw) == MAX_LINE_BYTES:
            if not raw.endswith(b"\n"):
                while True:
                    tail = stream.readline(MAX_LINE_BYTES + 1)
                    if not tail or tail.endswith(b"\n"):
                        break
            yield None
        else:
            yield raw


def _validate_line(raw: bytes | None) -> tuple[str, str, str]:
    if raw is None:
        raise ProbeError("OVERSIZED_LINE")
    if len(raw) > MAX_LINE_BYTES:
        raise ProbeError("OVERSIZED_LINE")
    try:
        decoded = raw.decode("utf-8", errors="strict").rstrip("\n")
    except UnicodeDecodeError as exc:
        raise ProbeError("INVALID_UTF8") from exc
    if decoded.endswith("\r"):
        decoded = decoded[:-1]
    fields = decoded.split("\t")
    if len(fields) != 3:
        raise ProbeError("COLUMN_COUNT")
    lemma, form, features = fields
    if not (lemma.strip() and form.strip() and _safe_text(lemma) and _safe_text(form)):
        raise ProbeError("INVALID_TEXT")
    tags = features.split(";")
    if not tags or not all(FEATURE.fullmatch(tag) for tag in tags):
        raise ProbeError("INVALID_TAG_SYNTAX")
    return lemma, form, features


def inspect(*, source: Path, expected_sha256: str, language: str,
            first_line: int, last_line: int) -> dict:
    """Inspect a SHA-pinned source shard, returning candidates NOT production forms.

    Line ranges are 1-based, inclusive. This validates syntax only; no
    morphology, POS, translation, or license claims are inferred.
    """
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise ProbeError("SOURCE_SHA_REQUIRED")
    if not isinstance(language, str) or not LANGUAGE.fullmatch(language):
        raise ProbeError("EXPLICIT_ISO639_3_LANGUAGE_REQUIRED")
    if (type(first_line) is not int or type(last_line) is not int
            or first_line < 1 or last_line < first_line
            or last_line - first_line + 1 > MAX_SHARD_ROWS):
        raise ProbeError("INVALID_BOUNDED_PARTITION")
    source = Path(source)
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
        raise ProbeError("UNSAFE_OR_OVERSIZED_SOURCE")
    actual_sha = sha256_stream(source)
    if actual_sha != expected_sha256:
        raise ProbeError("SOURCE_HASH_MISMATCH")

    counts = {"source_rows": 0, "candidate_rows": 0, "duplicate_rows": 0,
              "rejected_rows": 0}
    reasons: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()
    with source.open("rb") as stream:
        for line_no, raw in enumerate(_bounded_lines(stream), 1):
            if line_no < first_line:
                continue
            if line_no > last_line:
                break
            counts["source_rows"] += 1
            try:
                record = _validate_line(raw)
            except ProbeError as exc:
                counts["rejected_rows"] += 1
                reason = str(exc)
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            if record in seen:
                counts["duplicate_rows"] += 1
                continue
            seen.add(record)
            counts["candidate_rows"] += 1
    if counts["source_rows"] != last_line - first_line + 1:
        raise ProbeError("TRUNCATED_PARTITION")
    fingerprint = hashlib.sha256(json.dumps({
        "source_sha256": actual_sha, "language": language,
        "first_line": first_line, "last_line": last_line,
        "probe_schema": "unimorph-tsv-syntax-v1",
    }, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    return {
        "status": "INSPECTION_ONLY_RIGHTS_NOT_GRANTED",
        "language_iso639_3": language,
        "source_sha256": actual_sha,
        "partition_fingerprint": fingerprint,
        "first_line": first_line,
        "last_line": last_line,
        **counts,
        "rejection_reasons": dict(sorted(reasons.items())),
        "real_persisted_accepted": 0,
    }
