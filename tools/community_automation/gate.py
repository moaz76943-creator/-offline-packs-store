import argparse
import io
import json
import tarfile
import zipfile
import gzip
import os
import stat
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Direct invocation from any working directory, without replacing package imports.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from community.contributions.ingest import ingest, quarantine_submission, MAX_EXPANDED

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
    if not os.access(os.getcwd(), os.W_OK):
        raise RuntimeError('workspace access not authorized')
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
            infos = archive.infolist()
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError("invalid archive member count")
            expanded = 0
            for info in infos:
                expanded += info.file_size
                if info.file_size > MAX_EXPANDED or expanded > MAX_EXPANDED:
                    raise ValueError("archive expansion limit")
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode):
                    raise ValueError("archive links/directories forbidden")
                part = info.filename
                if "\\" in part or part.startswith(".") or ".." in part or part != Path(part).name:
                    raise ValueError("archive path traversal forbidden")

                if part.endswith(".svg"):
                    with archive.open(info) as stream:
                        svg = stream.read(info.file_size + 1)
                    if len(svg) != info.file_size:
                        raise ValueError("archive size mismatch")
                    validate_svg(svg)
    elif name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            expanded = 0
            count = 0
            for info in archive:
                count += 1
                expanded += info.size
                if count > MAX_MEMBERS:
                    raise ValueError("invalid archive member count")
                if info.size > MAX_EXPANDED or expanded > MAX_EXPANDED:
                    raise ValueError("archive expansion limit")
                if not info.isfile() or "\\" in info.name or info.name.startswith(".") or ".." in info.name or info.name != Path(info.name).name:
                    raise ValueError("archive path traversal forbidden")

                if info.isfile() and info.name.endswith(".svg"):
                    f = archive.extractfile(info)
                    if f:
                        with f:
                            svg = f.read(info.size + 1)
                        if len(svg) != info.size:
                            raise ValueError("archive size mismatch")
                        validate_svg(svg)

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
        try:
            quarantine_submission(args.submission, args.staging_root, str(exc))
        except Exception:
            # Missing, symlinked, or oversized submissions may be unreadable.
            # Preserve the original controlled rejection; no successful receipt.
            pass
        print("REJECTED:", exc)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
