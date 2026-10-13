"""Isolated, nonpublishing checks for the explicitly requested SQLite backup."""
import gzip
import hashlib
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backup_state import backup, main, REPO_ROOT, _verify


class SafeBackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'learning.sqlite'
        self.output = self.root / 'saved.sqlite.gz'
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE vocabulary(id INTEGER PRIMARY KEY, surface TEXT NOT NULL)')
            db.executemany('INSERT INTO vocabulary(surface) VALUES (?)',
                           [('Straße',), ('بيت',), ('日本語',)])
            db.commit()
        self.original = self.source.read_bytes()

    def restore_and_read(self):
        restored = self.root / 'restored.sqlite'
        restored.write_bytes(gzip.decompress(self.output.read_bytes()))
        with closing(sqlite3.connect(restored)) as db:
            return [row[0] for row in db.execute('SELECT surface FROM vocabulary ORDER BY id')]

    def test_snapshot_roundtrip_unicode_and_source_unchanged(self):
        receipt = backup(self.source, self.output)
        raw = gzip.decompress(self.output.read_bytes())
        self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['sqlite_bytes'], len(raw))
        self.assertEqual(self.restore_and_read(), ['Straße', 'بيت', '日本語'])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.output.read_bytes()[4:8], b'\x00\x00\x00\x00')

    def test_existing_output_never_overwritten(self):
        self.output.write_bytes(b'previous trusted backup')
        with self.assertRaises(FileExistsError):
            backup(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'previous trusted backup')

    def test_source_symlink_rejected_without_archive(self):
        alias = self.root / 'source-alias.sqlite'
        alias.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, 'not a symlink'):
            backup(alias, self.output)
        self.assertFalse(self.output.exists())

    def test_output_symlink_rejected_without_touching_target(self):
        target = self.root / 'other.sqlite.gz'
        target.write_bytes(b'preserve')
        self.output.symlink_to(target)
        with self.assertRaises(FileExistsError):
            backup(self.source, self.output)
        self.assertEqual(target.read_bytes(), b'preserve')

    def test_wal_content_is_included_in_snapshot(self):
        with closing(sqlite3.connect(self.source)) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute("INSERT INTO vocabulary(surface) VALUES ('السَّلَام')")
            conn.commit()
            backup(self.source, self.output)
            self.assertEqual(self.restore_and_read(),
                             ['Straße', 'بيت', '日本語', 'السَّلَام'])

    def test_foreign_key_corruption_refused(self):
        with closing(sqlite3.connect(self.source)) as conn:
            conn.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
            conn.execute('CREATE TABLE child(pid INTEGER REFERENCES parent(id))')
            conn.execute('INSERT INTO child(pid) VALUES (777)')
            conn.commit()
        with self.assertRaisesRegex(ValueError, 'foreign_key_check'):
            backup(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_foreign_key_check_stops_at_first_violation(self):
        class Result:
            def __init__(self, first):
                self.first = first
            def fetchone(self):
                return self.first
            def fetchall(self):
                raise AssertionError('unbounded materialization forbidden')
        class Db:
            def execute(self, sql):
                if sql == 'PRAGMA integrity_check':
                    return Result(('ok',))
                if sql == 'PRAGMA foreign_key_check':
                    return Result(('child', 1, 'parent', 0))
                raise AssertionError(sql)
        with self.assertRaisesRegex(ValueError, 'foreign_key_check'):
            _verify(Db())

    def test_corrupt_source_fail_closed(self):
        self.source.write_bytes(b'not a sqlite database')
        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            backup(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_reject_wrong_output_name_and_missing_parent(self):
        with self.assertRaisesRegex(ValueError, 'sqlite.gz'):
            backup(self.source, self.root / 'backup.gz')
        with self.assertRaisesRegex(ValueError, 'already exist'):
            backup(self.source, self.root / 'missing' / 'backup.sqlite.gz')

    def test_reject_repository_output(self):
        with self.assertRaisesRegex(ValueError, 'inside the repository'):
            backup(self.source, REPO_ROOT / 'forbidden.sqlite.gz')

    def test_cli_returns_success_without_github_or_shell(self):
        with patch('backup_state.os.system', side_effect=AssertionError('shell forbidden'), create=True):
            self.assertEqual(main(['--source', str(self.source), '--output', str(self.output)]), 0)
        self.assertTrue(self.output.exists())

    def test_failed_write_does_not_leave_archive(self):
        original = gzip.GzipFile.write
        def failed_write(self_gzip, data):
            raise OSError('simulated write failure')
        with patch.object(gzip.GzipFile, 'write', failed_write):
            with self.assertRaisesRegex(OSError, 'simulated write failure'):
                backup(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
