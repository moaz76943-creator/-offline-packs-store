"""Focused SQLite v2 compatibility regressions adapted from legacy Jules PRs.

Inputs are synthetic and confined to temporary directories. No production
manifest, pack, corpus, CI workflow or source ledger may be modified here.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compile_store_packs
from pack_v2.pipeline import MAX_JSON, compact, compile_pack, read_json, sha


class CanonicalV2UtilitiesTest(unittest.TestCase):
    def test_compact_json_is_sorted_utf8_and_has_no_optional_whitespace(self):
        data = {'b': 'بيت', 'a': 'Straße'}
        self.assertEqual(compact(data), '{"a":"Straße","b":"بيت"}')
        self.assertEqual(compact(data).encode('utf-8'),
                         '{"a":"Straße","b":"بيت"}'.encode('utf-8'))

    def test_compact_json_rejects_nonfinite_numbers(self):
        for number in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(number=str(number)):
                with self.assertRaises(ValueError):
                    compact({'value': number})

    def test_current_hash_apis_agree_with_sha256_for_unicode_bytes(self):
        for raw in (b'', b'hello world', 'café بيت'.encode('utf-8')):
            with self.subTest(raw=raw):
                expected = hashlib.sha256(raw).hexdigest()
                self.assertEqual(sha(raw), expected)
                self.assertEqual(compile_store_packs.file_hash(raw), expected)


class AtomicWriteCompatibilityTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'new' / 'candidate.pack.gz'

    def test_new_write_creates_bytes_without_extra_files(self):
        self.assertTrue(compile_store_packs.atomic_write(self.path, b'first'))
        self.assertEqual(self.path.read_bytes(), b'first')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unchanged_bytes_skip_atomic_replacement(self):
        self.assertTrue(compile_store_packs.atomic_write(self.path, b'existing'))
        with patch.object(compile_store_packs.os, 'replace',
                          side_effect=AssertionError('unexpected replacement')):
            self.assertFalse(compile_store_packs.atomic_write(self.path, b'existing'))
        self.assertEqual(self.path.read_bytes(), b'existing')

    def test_changed_bytes_replace_atomically_and_clean_temp_files(self):
        compile_store_packs.atomic_write(self.path, b'old')
        self.assertTrue(compile_store_packs.atomic_write(self.path, b'new'))
        self.assertEqual(self.path.read_bytes(), b'new')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_replace_preserves_existing_bytes_and_cleans_stage(self):
        compile_store_packs.atomic_write(self.path, b'preserve')
        with patch.object(compile_store_packs.os, 'replace',
                          side_effect=OSError('simulated rename failure')):
            with self.assertRaisesRegex(OSError, 'simulated rename failure'):
                compile_store_packs.atomic_write(self.path, b'replacement')
        self.assertEqual(self.path.read_bytes(), b'preserve')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


class CanonicalSourceAdmissionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = self.root / 'de.json'

    def test_utf8_source_json_retains_attested_text(self):
        source = {'lexemes': [{'surface': 'Straße بيت'}]}
        self.src.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
        self.assertEqual(read_json(self.src), source)

    def test_duplicate_source_json_keys_fail_closed(self):
        self.src.write_text('{"surface":"Haus","surface":"Wohnung"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            read_json(self.src)

    def test_nonfinite_source_json_fails_closed(self):
        for constant in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(constant=constant):
                self.src.write_text('{"rank":' + constant + '}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'invalid JSON numeric constant'):
                    read_json(self.src)

    def test_oversized_source_json_fails_before_parsing(self):
        with self.src.open('wb') as f:
            f.truncate(MAX_JSON + 1)
        with self.assertRaisesRegex(ValueError, 'source JSON exceeds limit'):
            read_json(self.src)

    def test_unverified_legacy_sqlite_is_not_silently_republished(self):
        sqlite_source = self.root / 'de.sqlite'
        sqlite_source.write_bytes(b'untrusted legacy source')
        with self.assertRaisesRegex(ValueError, 'requires canonical lexical JSON'):
            compile_pack(sqlite_source, 'de', self.root, self.root, fixture_only=True)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['de.sqlite'])


if __name__ == '__main__':
    unittest.main()
