"""Fail-closed complementary transport; no production dispatch, rights approval or release."""
from __future__ import annotations
import bz2
import gzip
import hashlib
import http.client
import ipaddress
import json
import lzma
import os
import re
import shutil
import socket
import ssl
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from tools.gha_factory.admission import pipeline as admission

CHUNK = 256 * 1024
MAX_LINE = 1024 * 1024
MAX_SOURCE = 16 * 1024**3
MAX_SHARDS = 100000
SHA = re.compile(r"[0-9a-f]{64}\Z")
HOST = re.compile(r"[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]\Z")
FORMATS = {"jsonl": open, "jsonl.gz": gzip.open, "jsonl.bz2": bz2.open, "jsonl.xz": lzma.open}


class Blocked(ValueError):
    """Never promote rejected bytes or mismatched checkpoint state."""


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise Blocked("BLOCKED_SOURCE: duplicate JSON key")
        obj[key] = value
    return obj


def strict_json(raw):
    try:
        return json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError) as exc:
        raise Blocked("BLOCKED_SOURCE: invalid UTF-8/JSON") from exc


def reviewed_target(url, allowed_hosts):
    try:
        u = urlsplit(url)
        host = u.hostname
        if (not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url)
                or u.scheme != "https" or not host or u.port not in (None, 443)
                or u.username or u.password or u.fragment or u.netloc.endswith(".")
                or host != host.lower() or not HOST.fullmatch(host)
                or host not in allowed_hosts or ".." in host or "." not in host):
            raise ValueError("unsafe endpoint")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP literal")
        if any(k.split("=", 1)[0].lower() in
               {"token", "key", "signature", "password", "auth", "access_token"}
               for k in u.query.split("&") if k):
            raise ValueError("credential in URL")
        return host, (u.path or "/") + ("?" + u.query if u.query else "")
    except (ValueError, TypeError, AttributeError) as exc:
        raise Blocked("BLOCKED_SOURCE: unreviewed HTTPS host") from exc


def public_ips(host, resolver=socket.getaddrinfo):
    try:
        ips = sorted({ipaddress.ip_address(record[4][0])
                      for record in resolver(host, 443, type=socket.SOCK_STREAM)}, key=str)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise Blocked("BLOCKED_SOURCE: DNS failed") from exc
    if not ips or not all(ip.is_global for ip in ips):
        raise Blocked("BLOCKED_SOURCE: private/reserved DNS result")
    return [str(ip) for ip in ips]


class PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        last = None
        for address in public_ips(self.host):
            try:
                raw = socket.create_connection((address, 443), timeout=self.timeout)
                try:
                    self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                except BaseException:
                    raw.close()
                    raise
                return
            except OSError as exc:
                last = exc
        raise Blocked("BLOCKED_SOURCE: reviewed host unreachable") from last


@dataclass(frozen=True)
class Approved:
    source_id: str
    version: str
    language: str
    url: str
    sha256: str
    size: int
    rights_sha256: str
    decision_url: str
    hosts: tuple[str, ...]

    @property
    def identity(self):
        return hashlib.sha256(canonical([self.source_id, self.version, self.language,
                                         self.url, self.sha256, self.size,
                                         self.rights_sha256])).hexdigest()


def approved_source(root, source_id, version, language, url, sha256, size, hosts):
    """Exact Route 05/GHA-01 ledger/registry binding; cannot grant rights."""
    root = Path(root).resolve()
    try:
        if (type(size) is not int or not 0 < size <= MAX_SOURCE
                or not isinstance(sha256, str) or not SHA.fullmatch(sha256)):
            raise ValueError("unbounded size/hash")
        if language not in admission.registry_metadata(root):
            raise ValueError("unregistered language")
        ledger = strict_json((root / "legal/ledger/sources.json").read_bytes())
        if ledger.get("schema_version") != "1.0.0" or not isinstance(ledger.get("sources"), list):
            raise ValueError("invalid ledger")
        matches = [s for s in ledger["sources"]
                   if isinstance(s, dict) and s.get("source_id") == source_id]
        if len(matches) != 1:
            raise ValueError("missing or duplicate source")
        s = matches[0]
        r, rights, review = s["retrieval"], s["license"], s["review"]
        if (s.get("status") != "APPROVED_FOR_REDISTRIBUTION"
                or s.get("kind") != "dictionary" or s.get("dataset_version") != version
                or r.get("url") != url or r.get("sha256") != sha256
                or rights.get("id") not in admission.ROUTE05_LICENSES
                or rights["id"] == "GFDL-1.3-only"
                or not s.get("publisher") or not s.get("alterations")
                or not r.get("identity") or not r.get("date")
                or not review.get("reviewer")
                or not all(admission.https_url(x) for x in
                           (s.get("origin_url"), url, rights.get("evidence_url"),
                            review.get("decision_url")))):
            raise ValueError("unreviewed rights/version")
        if rights["id"] == "PUBLIC-DOMAIN" and not all(
                (rights.get("public_domain_proof") or {}).get(k)
                for k in ("jurisdiction", "legal_basis", "work_date")):
            raise ValueError("no PD proof")
        evidence_host = urlsplit(rights["evidence_url"]).hostname.lower()
        if any(x in evidence_host for x in ("creativecommons.org", "gnu.org")):
            raise ValueError("generic rights page is not source evidence")
        admission.checked_file(root, rights["evidence_path"], rights["evidence_sha256"],
                               "source-specific license evidence")
        rel = r["artifact_path"]
        if (not isinstance(rel, str) or not rel or Path(rel).is_absolute()
                or ".." in Path(rel).parts or ".git" in Path(rel).parts):
            raise ValueError("unsafe original source path")
        if (root / rel).exists():
            admission.checked_file(root, rel, sha256, "source")
        reviewed_target(url, frozenset(hosts))
        return Approved(source_id, version, language, url, sha256, size,
                        rights["evidence_sha256"], review["decision_url"], tuple(sorted(hosts)))
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        raise Blocked("BLOCKED_SOURCE: Route 05/GHA-01 exact approval missing") from exc


def verified(path, source):
    p = Path(path)
    if (p.is_symlink() or not p.is_file() or p.stat().st_size != source.size
            or sha_file(p) != source.sha256):
        raise Blocked("BLOCKED_SOURCE: incomplete/wrong source bytes")


def write_once(path, payload):
    """Atomic hard link: stale, foreign and partially written final bytes cannot overwrite."""
    path = Path(path)
    if path.is_symlink():
        raise Blocked("BLOCKED_SOURCE: symlink destination")
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".snap-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise Blocked("BLOCKED_SOURCE: immutable checkpoint collision")
    finally:
        Path(temp).unlink(missing_ok=True)


def download(source, target, attempts=3, connection_factory=None):
    """Optional HTTPS transport; NO production CLI/CI call. .part is never trusted."""
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise Blocked("BLOCKED_SOURCE: unbounded retries")
    host, path = reviewed_target(source.url, frozenset(source.hosts))
    target = Path(target)
    if target.is_symlink() or not target.parent.is_dir():
        raise Blocked("BLOCKED_SOURCE: unsafe target")
    begin_cpu, begin_wall = time.process_time(), time.monotonic()
    def report(bytes_read, retry):
        return {"source_sha256": source.sha256, "source_bytes": source.size,
                "downloaded_bytes": bytes_read, "retries": retry, "retry_state": "COMPLETE",
                "cpu_seconds": round(time.process_time() - begin_cpu, 6),
                "wall_seconds": round(time.monotonic() - begin_wall, 6),
                "free_disk_bytes": shutil.disk_usage(target.parent).free}
    if target.exists():
        verified(target, source)
        return report(0, 0)
    part = target.with_name(target.name + ".part")
    stamp = target.with_name(target.name + ".identity.json")
    if part.is_symlink() or stamp.is_symlink():
        raise Blocked("BLOCKED_SOURCE: checkpoint symlink")
    identity = canonical({"identity": source.identity, "size": source.size})
    if stamp.exists():
        if stamp.read_bytes() != identity or (part.exists() and not part.is_file()):
            raise Blocked("BLOCKED_SOURCE: foreign partial download")
    else:
        if part.exists():
            raise Blocked("BLOCKED_SOURCE: unbound partial")
        write_once(stamp, identity)
    transferred = 0
    for retry in range(attempts):
        offset = part.stat().st_size if part.exists() else 0
        if offset > source.size:
            raise Blocked("BLOCKED_SOURCE: excess partial bytes")
        if offset == source.size:
            verified(part, source)
            os.replace(part, target)
            stamp.unlink()
            return report(transferred, retry)
        conn = None
        try:
            conn = (connection_factory(host) if connection_factory else
                    PinnedHTTPS(host, timeout=35, context=ssl.create_default_context()))
            headers = {"User-Agent": "public-snapshot-transport/1", "Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-{source.size - 1}"
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            h = {k.lower(): v for k, v in resp.getheaders()}
            if (resp.status != (206 if offset else 200)
                    or h.get("content-length") != str(source.size - offset)
                    or h.get("content-encoding", "identity") != "identity"
                    or "transfer-encoding" in h
                    or (offset and h.get("content-range") !=
                        f"bytes {offset}-{source.size - 1}/{source.size}")):
                raise Blocked("BLOCKED_SOURCE: redirect/range/length/encoding")
            with part.open("ab" if offset else "wb") as out:
                while offset < source.size:
                    chunk = resp.read(min(CHUNK, source.size - offset))
                    if not chunk:
                        raise OSError("partial transfer")
                    out.write(chunk)
                    transferred += len(chunk)
                    offset += len(chunk)
                if resp.read(1):
                    raise Blocked("BLOCKED_SOURCE: extra response bytes")
                out.flush()
                os.fsync(out.fileno())
            verified(part, source)
            os.replace(part, target)
            stamp.unlink()
            return report(transferred, retry)
        except (OSError, http.client.HTTPException) as exc:
            if retry + 1 == attempts:
                raise Blocked("BLOCKED_SOURCE: retry exhausted") from exc
        finally:
            if conn:
                conn.close()
    raise Blocked("BLOCKED_SOURCE: download incomplete")


def validate_row(raw, source):
    if (len(raw) > MAX_LINE or not raw.endswith(b"\n") or raw.startswith(b"\xef\xbb\xbf")
            or b"\x00" in raw):
        raise Blocked("BLOCKED_SOURCE: bad JSONL framing")
    row = strict_json(raw)
    if not isinstance(row, dict) or row.get("lang_code") != source.language:
        raise Blocked("BLOCKED_SOURCE: wrong source language")
    if (row.get("source_id", source.source_id) != source.source_id
            or row.get("dataset_version", source.version) != source.version):
        raise Blocked("BLOCKED_SOURCE: row provenance mismatch")


def stage(source, input_path, store, fmt="jsonl", shard_rows=10000,
          max_expanded=MAX_SOURCE, fault_after_shards=None):
    """Cross-run replay over external persistent mount; no runner temp durability claim."""
    if (fmt not in FORMATS or type(shard_rows) is not int or not 1 <= shard_rows <= 10000
            or type(max_expanded) is not int or not 0 < max_expanded <= MAX_SOURCE):
        raise Blocked("BLOCKED_SOURCE: shard/decompression budget")
    verified(input_path, source)
    store = Path(store)
    if not store.is_dir() or store.is_symlink():
        raise Blocked("BLOCKED_DEPENDENCY_STORAGE: unmounted store")
    for name in ("shards", "checkpoints", "manifests"):
        d = store / name
        d.mkdir(exist_ok=True)
        if d.is_symlink():
            raise Blocked("BLOCKED_SOURCE: store symlink")
    checks = store / "checkpoints" / source.identity
    checks.mkdir(exist_ok=True)
    if checks.is_symlink():
        raise Blocked("BLOCKED_SOURCE: checkpoint symlink")
    cpu_start, wall_start = time.process_time(), time.monotonic()
    partitions, total, expanded, replayed, committed = [], 0, 0, 0, 0
    with FORMATS[fmt](input_path, "rb") as stream:
        eof = False
        while not eof:
            fd, name = tempfile.mkstemp(dir=store / "shards", prefix=".shard-")
            temp = Path(name)
            count, byte_count, h = 0, 0, hashlib.sha256()
            try:
                with os.fdopen(fd, "wb") as output:
                    while count < shard_rows:
                        raw = stream.readline(MAX_LINE + 1)
                        if not raw:
                            eof = True
                            break
                        expanded += len(raw)
                        if expanded > max_expanded:
                            raise Blocked("BLOCKED_SOURCE: expanded byte budget")
                        validate_row(raw, source)
                        output.write(raw)
                        h.update(raw)
                        count += 1
                        byte_count += len(raw)
                    output.flush()
                    os.fsync(output.fileno())
                if not count:
                    break
                if len(partitions) >= MAX_SHARDS:
                    raise Blocked("BLOCKED_SOURCE: too many shards")
                index, digest = len(partitions), h.hexdigest()
                blob = store / "shards" / (digest + ".jsonl")
                checkpoint = checks / f"{index:08d}.json"
                entry = {"schema_version": "snapshot-transport.v1", "source_identity": source.identity,
                         "source_id": source.source_id, "dataset_version": source.version,
                         "source_sha256": source.sha256, "language": source.language,
                         "index": index, "rows": count, "bytes": byte_count,
                         "first_row": total + 1, "last_row": total + count, "sha256": digest}
                data = canonical(entry)
                if checkpoint.exists():
                    if (checkpoint.is_symlink() or checkpoint.read_bytes() != data
                            or blob.is_symlink() or not blob.is_file()
                            or sha_file(blob) != digest):
                        raise Blocked("BLOCKED_SOURCE: replay digest/identity mismatch")
                    replayed += 1
                else:
                    if blob.is_symlink():
                        raise Blocked("BLOCKED_SOURCE: content blob symlink")
                    try:
                        os.link(temp, blob)
                    except FileExistsError:
                        if blob.is_symlink() or sha_file(blob) != digest:
                            raise Blocked("BLOCKED_SOURCE: changed shared blob")
                    write_once(checkpoint, data)
                    committed += 1
                partitions.append(entry)
                total += count
                if fault_after_shards is not None and committed >= fault_after_shards:
                    raise RuntimeError("synthetic worker termination")
            finally:
                temp.unlink(missing_ok=True)
    if not total:
        raise Blocked("BLOCKED_SOURCE: empty corpus")
    manifest = {"schema_version": "snapshot-transport.v1", "status": "STAGED_ONLY",
                "publication_approved": False, "source_id": source.source_id,
                "dataset_version": source.version, "language": source.language,
                "source_url": source.url, "source_sha256": source.sha256,
                "source_bytes": source.size, "source_identity": source.identity,
                "rights_sha256": source.rights_sha256, "format": fmt,
                "shard_rows": shard_rows, "input_rows": total,
                "expanded_bytes": expanded, "partitions": partitions}
    out = canonical(manifest)
    write_once(store / "manifests" / (source.identity + ".json"), out)
    return {"status": "STAGED_ONLY", "source_identity": source.identity,
            "source_sha256": source.sha256, "verified_input_bytes": source.size,
            "manifest_sha256": hashlib.sha256(out).hexdigest(),
            "input_rows": total, "shards": len(partitions),
            "replayed_shards": replayed, "new_shards": committed,
            "cpu_seconds": round(time.process_time() - cpu_start, 6),
            "wall_seconds": round(time.monotonic() - wall_start, 6),
            "free_disk_bytes": shutil.disk_usage(store).free,
            "retry_state": "COMPLETE", "persistent_backend_verified": False}
