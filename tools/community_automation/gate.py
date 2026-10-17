import argparse
import io
import json
import tarfile
import zipfile
import gzip
import os
import stat
from pathlib import Path

from community.contributions.ingest import ingest, quarantine_submission

MAX_INPUT = 8 * 1024 * 1024
MAX_MEMBERS = 128

def validate_svg(data):
    try:
        content = data.decode("utf-8")
        if "<script" in content.lower() or "javascript:" in content.lower():
            raise ValueError("unsafe svg: scripts forbidden")
        if "<foreignobject" in content.lower():
            raise ValueError("unsafe svg: foreignObject forbidden")
        if "http://" in content.lower() or "https://" in content.lower():
            raise ValueError("unsafe svg: external references forbidden")
    except UnicodeDecodeError:
        raise ValueError("unsafe svg: invalid utf-8 encoding")

def process_bundle(source, staging_root):
    # This logic sits alongside community/contributions/ingest.py,
    # but we will likely want to process .vct and .svg files too.
    source_path = Path(source)
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("symlink or missing submission")

    # Check if the bundle has unsafe files
    fd = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size > MAX_INPUT or not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("unsafe or oversized submission")
        with os.fdopen(fd, "rb") as f:
            fd = -1
            data = f.read(MAX_INPUT + 1)
    finally:
        if fd >= 0:
            os.close(fd)

    if len(data) > MAX_INPUT:
        raise ValueError("input exceeds size limit")

    name = str(source)
    if name.endswith(".svg"):
        validate_svg(data)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode):
                    raise ValueError("archive links/directories forbidden")
                part = info.filename
                if "\\" in part or part.startswith(".") or ".." in part or part != Path(part).name:
                    raise ValueError("archive path traversal forbidden")

                if part.endswith(".svg"):
                    with archive.open(info) as f:
                        validate_svg(f.read())
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for info in archive:
                if not info.isfile() or "\\" in info.name or info.name.startswith(".") or ".." in info.name or info.name != Path(info.name).name:
                    raise ValueError("archive path traversal forbidden")

                if info.isfile() and info.name.endswith(".svg"):
                    f = archive.extractfile(info)
                    if f:
                        validate_svg(f.read())

    return ingest(source, staging_root)

def main(argv=None):
    parser = argparse.ArgumentParser(description="Community automation gate.")
    parser.add_argument("submission", type=Path)
    parser.add_argument("--staging-root", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        receipt = process_bundle(args.submission, args.staging_root)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except Exception as exc:
        quarantine_submission(args.submission, args.staging_root, str(exc))
        print("REJECTED:", exc)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
