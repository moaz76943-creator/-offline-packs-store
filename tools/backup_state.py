#!/usr/bin/env python3
"""Explicit, offline, bounded SQLite backup. Never scans, pushes, or publishes data."""
import argparse
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from urllib.parse import quote

MAX_SQLITE_BYTES = 64 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parent.parent


def _verify(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('SQLite integrity_check failed')
    if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise ValueError('SQLite foreign_key_check failed')


def backup(source: Path, output: Path):
    """Return a digest receipt; never overwrite an output or alter the source."""
    source, output = Path(source), Path(output)
    if source.is_symlink() or not source.is_file():
        raise ValueError('source must be an existing regular SQLite file, not a symlink')
    if source.stat().st_size > MAX_SQLITE_BYTES:
        raise ValueError('source exceeds backup size limit')
    if output.suffix != '.gz' or not output.name.endswith('.sqlite.gz'):
        raise ValueError('output must end in .sqlite.gz')
    if output.is_symlink() or output.exists():
        raise FileExistsError('output already exists or is a symlink')
    if not output.parent.is_dir():
        raise ValueError('output directory must already exist')
    if output.resolve() == source.resolve():
        raise ValueError('source and output must differ')
    if output.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise ValueError('refusing to write backups inside the repository')

    uri = 'file:' + quote(str(source.resolve()), safe='/') + '?mode=ro'
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.sqlite-backup-') as td:
        snapshot = Path(td) / 'snapshot.sqlite'
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
            _verify(db)
            pages = db.execute('PRAGMA page_count').fetchone()[0]
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            if pages * page_size > MAX_SQLITE_BYTES:
                raise ValueError('logical SQLite exceeds backup size limit')
            with closing(sqlite3.connect(snapshot)) as copy:
                db.backup(copy)
        if snapshot.stat().st_size > MAX_SQLITE_BYTES:
            raise ValueError('snapshot exceeds backup size limit')
        with closing(sqlite3.connect(f'file:{quote(str(snapshot), safe="/")}?mode=ro', uri=True)) as copy:
            _verify(copy)

        digest = hashlib.sha256()
        created = False
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(output, flags, 0o600)
            created = True
            with os.fdopen(fd, 'wb') as binary:
                with gzip.GzipFile(filename='', mode='wb', fileobj=binary, mtime=0) as zipped:
                    with snapshot.open('rb') as raw:
                        for block in iter(lambda: raw.read(65536), b''):
                            digest.update(block)
                            zipped.write(block)
                binary.flush()
                os.fsync(binary.fileno())
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
        return {'sha256': digest.hexdigest(), 'sqlite_bytes': snapshot.stat().st_size,
                'archive_bytes': output.stat().st_size}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(backup(args.source, args.output), sort_keys=True))
    except (OSError, sqlite3.Error, ValueError) as exc:
        print('BACKUP_REFUSED: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
