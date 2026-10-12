import tempfile
import unittest
import hashlib
from pathlib import Path
from compile_store_packs import verify_legacy_files, digest, REPO_CDN

class VerifyLegacyFilesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output_dir = Path(self.temp.name)

    def _create_dummy_pack(self, filename, content=b'dummy data'):
        filepath = self.output_dir / filename
        filepath.write_bytes(content)
        return {
            'pack_file': filename,
            'size_bytes': len(content),
            'sha256': digest(content)
        }

    def test_valid_legacy_files(self):
        item = self._create_dummy_pack('valid.pack.gz')
        # Should not raise an exception
        verify_legacy_files([item], self.output_dir)

    def test_non_dict_entry(self):
        with self.assertRaisesRegex(ValueError, 'legacy manifest language entry must be an object'):
            verify_legacy_files(['not a dict'], self.output_dir)

    def test_unpublished_language(self):
        # Entry with none of the required keys
        # Should be skipped without errors
        verify_legacy_files([{'other_key': 'value'}], self.output_dir)

    def test_incomplete_metadata(self):
        # Entry with some but not all required keys
        with self.assertRaisesRegex(ValueError, 'incomplete legacy pack integrity metadata'):
            verify_legacy_files([{'pack_file': 'some.pack.gz', 'size_bytes': 100}], self.output_dir)

    def test_unsafe_filename(self):
        item = self._create_dummy_pack('unsafe.pack.gz')

        # Test non-string filename
        item_non_string = item.copy()
        item_non_string['pack_file'] = 123
        with self.assertRaisesRegex(ValueError, 'unsafe legacy pack filename'):
            verify_legacy_files([item_non_string], self.output_dir)

        # Test wrong extension
        item_wrong_ext = item.copy()
        item_wrong_ext['pack_file'] = 'file.txt'
        with self.assertRaisesRegex(ValueError, 'unsafe legacy pack filename'):
            verify_legacy_files([item_wrong_ext], self.output_dir)

        # Test path separators
        item_path = item.copy()
        item_path['pack_file'] = 'dir/file.pack.gz'
        with self.assertRaisesRegex(ValueError, 'unsafe legacy pack filename'):
            verify_legacy_files([item_path], self.output_dir)

    def test_url_mismatch(self):
        item = self._create_dummy_pack('url.pack.gz')
        item['pack_url'] = 'https://wrong-url.com/url.pack.gz'
        with self.assertRaisesRegex(ValueError, 'legacy package URL mismatch'):
            verify_legacy_files([item], self.output_dir)

    def test_missing_file(self):
        item = {
            'pack_file': 'missing.pack.gz',
            'size_bytes': 100,
            'sha256': 'fakehash'
        }
        with self.assertRaisesRegex(FileNotFoundError, 'missing legacy pack'):
            verify_legacy_files([item], self.output_dir)

    def test_size_mismatch(self):
        item = self._create_dummy_pack('size.pack.gz')
        item['size_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'legacy package checksum/size mismatch'):
            verify_legacy_files([item], self.output_dir)

    def test_hash_mismatch(self):
        item = self._create_dummy_pack('hash.pack.gz')
        item['sha256'] = 'wronghash'
        with self.assertRaisesRegex(ValueError, 'legacy package checksum/size mismatch'):
            verify_legacy_files([item], self.output_dir)

if __name__ == '__main__':
    unittest.main()
