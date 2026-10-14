"""Source-accurate attribution output; never approves redistribution."""
import argparse
import json
import os
import secrets
import stat
from pathlib import Path

from tools.contribution_gate.evidence import (
    exact_source_reference, verified_sources
)

def _write_notices_safely(out_dir, files):
    """Stage notices with fd-relative, no-follow operations; manifest is written last.

    Neither output directory components nor existing output files may be symlinks.
    A completed attribution.json is the final commit marker of the batch.
    """
    directory = Path(out_dir).absolute()
    if ".." in directory.parts:
        raise ValueError("Parent traversal in attribution output path")
    names = list(files)
    if any(not name or name in (".", "..") or "/" in name or "\\" in name for name in names):
        raise ValueError("Unsafe attribution output filename")
    if "attribution.json" not in files:
        raise ValueError("Attribution manifest required")

    folder_flag = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    folder_fd = os.open("/", folder_flag)
    staged = {}
    try:
        for part in directory.parts[1:]:
            if part in ("", "."):
                continue
            try:
                next_fd = os.open(part, folder_flag, dir_fd=folder_fd)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=folder_fd)
                next_fd = os.open(part, folder_flag, dir_fd=folder_fd)
            os.close(folder_fd)
            folder_fd = next_fd
        # Preflight all destinations before changing any of them.
        for name in names:
            try:
                info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Attribution destination is a symlink or non-file: " + name)
        for name in names:
            temporary = ".rights-attribution-" + secrets.token_hex(16)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode=0o600, dir_fd=folder_fd)
            staged[name] = temporary
            with os.fdopen(fd, "wb") as handle:
                handle.write(files[name].encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        for name in [n for n in names if n != "attribution.json"] + ["attribution.json"]:
            os.replace(staged[name], name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
            del staged[name]
    finally:
        for temporary in staged.values():
            try:
                os.unlink(temporary, dir_fd=folder_fd)
            except FileNotFoundError:
                pass
        os.close(folder_fd)


def generate_attribution(ledger_path, refs_path, out_dir, *, repo_root=None):
    if repo_root is None:
        raise ValueError("repo_root required to verify original evidence bytes")
    ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    sources = verified_sources(ledger, repo_root)
    refs = json.loads(Path(refs_path).read_text(encoding="utf-8"))
    if not isinstance(refs, list) or not refs:
        raise ValueError("Nonempty source references required")
    unique = set()
    records = []
    # Validate the *complete* batch before writing a single file.
    for ref in refs:
        source = exact_source_reference(ref, sources)
        sid = source["source_id"]
        if sid in unique:
            raise ValueError("Duplicate source reference " + sid)
        if not source.get("publisher"):
            raise ValueError("Missing publisher for source " + sid)
        if not source.get("license") or not source["license"].get("id"):
            raise ValueError("Missing license metadata for source " + sid)
        unique.add(sid)
        records.append({
            "source_id": sid, "publisher": source["publisher"],
            "origin_url": source["origin_url"], "dataset_version": source["dataset_version"],
            "artifact_sha256": source["retrieval"]["sha256"],
            "retrieval_identity": source["retrieval"]["identity"],
            "retrieval_url": source["retrieval"]["url"],
            "license_id": source["license"]["id"],
            "license_evidence_url": source["license"]["evidence_url"],
            "license_evidence_sha256": source["license"]["evidence_sha256"],
            "alterations": source["alterations"],
            "review": source["review"],
            "public_domain_proof": source["license"].get("public_domain_proof"),
            "notice_file": sid + "_notice.txt"
        })
    records.sort(key=lambda r: r["source_id"])
    notices = {}
    for r in records:
        lines = [
            "Source: " + r["source_id"],
            "Publisher: " + r["publisher"],
            "Origin: " + r["origin_url"],
            "Version: " + r["dataset_version"],
            "Retrieved snapshot: " + r["retrieval_identity"],
            "Snapshot SHA-256: " + r["artifact_sha256"],
            "License: " + r["license_id"],
            "Source-specific rights: " + r["license_evidence_url"],
            "Rights proof SHA-256: " + r["license_evidence_sha256"],
        ]
        if r["license_id"] in ("CC-BY-SA-4.0", "GFDL-1.3-only"):
            lines.append("Alterations: " + "; ".join(r["alterations"]))
        lines.append("Independent review: " + r["review"]["reviewer"] + " " + r["review"]["decision_url"])
        if r["license_id"] == "PUBLIC-DOMAIN" and r.get("public_domain_proof"):
            lines.append("Public-domain basis: " + json.dumps(r["public_domain_proof"], sort_keys=True))
        notices[r["notice_file"]] = "\n".join(lines) + "\n"
    notices["attribution.json"] = json.dumps(
        records, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    _write_notices_safely(out_dir, notices)
    return records

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--refs", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        generate_attribution(args.ledger, args.refs, args.out_dir, repo_root=args.repo_root)
    except (ValueError, TypeError, OSError) as exc:
        parser.exit(1, "BLOCKED: " + str(exc) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
