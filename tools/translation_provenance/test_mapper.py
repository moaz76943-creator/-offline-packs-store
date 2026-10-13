import unittest
import json
from io import StringIO
from tools.translation_provenance.mapper import map_provenance

class TestTranslationProvenanceMapper(unittest.TestCase):
    def setUp(self):
        self.sources_manifest = {
            "sources": [
                {
                    "source_id": "src_1",
                    "dataset_version": "1.0",
                    "publisher": "Test Publisher",
                    "origin_url": "https://example.com/src1",
                    "license": {"id": "CC-BY-4.0"},
                    "retrieval": {"sha256": "abcdef123456"}
                },
                {
                    "source_id": "src_missing_license",
                    "dataset_version": "1.0",
                    "publisher": "Test Publisher",
                    "origin_url": "https://example.com/src2",
                    "retrieval": {"sha256": "123456abcdef"}
                }
            ]
        }

    def _run_mapper(self, lines):
        stream = StringIO("\n".join(json.dumps(line) for line in lines))
        return list(map_provenance(stream, self.sources_manifest))

    def test_valid_translation(self):
        lines = [
            {"type": "sense", "sense_id": "sense_a", "language": "en"},
            {"type": "sense", "sense_id": "sense_b", "language": "fr"},
            {
                "type": "translation",
                "translation_id": "tr_1",
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0",
                    "artifact_sha256": "abcdef123456"
                }
            }
        ]
        results = self._run_mapper(lines)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res["translation_id"], "tr_1")
        self.assertEqual(res["from_language"], "en")
        self.assertEqual(res["to_language"], "fr")
        self.assertEqual(res["license_id"], "CC-BY-4.0")
        self.assertTrue("provenance_hash" in res)

    def test_source_mismatch_version(self):
        lines = [
            {
                "type": "translation",
                "translation_id": "tr_2",
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "from_language": "en",
                "to_language": "fr",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "2.0" # Mismatch
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Mismatched dataset version"):
            self._run_mapper(lines)

    def test_source_mismatch_hash(self):
        lines = [
            {
                "type": "translation",
                "translation_id": "tr_3",
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "from_language": "en",
                "to_language": "fr",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0",
                    "artifact_sha256": "badhash" # Mismatch
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Mismatched source hash"):
            self._run_mapper(lines)

    def test_invalid_language_direction(self):
        lines = [
            {"type": "sense", "sense_id": "sense_c", "language": "en"},
            {"type": "sense", "sense_id": "sense_d", "language": "en"},
            {
                "type": "translation",
                "translation_id": "tr_4",
                "from_sense_id": "sense_c",
                "to_sense_id": "sense_d",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0"
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Invalid language direction"):
            self._run_mapper(lines)

    def test_missing_licensing(self):
        lines = [
            {
                "type": "translation",
                "translation_id": "tr_5",
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "from_language": "en",
                "to_language": "fr",
                "source": {
                    "source_id": "src_missing_license",
                    "dataset_version": "1.0"
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Missing licensing evidence"):
            self._run_mapper(lines)


    def test_orphan_translation(self):
        lines = [
            {"type": "sense", "sense_id": "sense_a", "language": "en"},
            # missing sense_b
            {
                "type": "translation",
                "translation_id": "tr_6",
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0"
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Orphan translation"):
            self._run_mapper(lines)

    def test_conflicting_ids(self):
        lines = [
            {"type": "sense", "sense_id": "sense_a", "language": "en"},
            {"type": "sense", "sense_id": "sense_b", "language": "fr"},
            {
                "type": "translation",
                "translation_id": "tr_1", # same id
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0"
                }
            },
            {
                "type": "translation",
                "translation_id": "tr_1", # same id again
                "from_sense_id": "sense_a",
                "to_sense_id": "sense_b",
                "source": {
                    "source_id": "src_1",
                    "dataset_version": "1.0"
                }
            }
        ]
        with self.assertRaisesRegex(ValueError, "Duplicate translation_id"):
            self._run_mapper(lines)

    def test_homographs_regional_variants(self):
        # Support distinct senses for homographs and polysemous words.
        # Preserve regional variants and contextual translation labels.
        # This is just demonstrating that distinct senses and languages are processed properly
        lines = [
            {"type": "sense", "sense_id": "sense_bat_animal", "language": "en-US"},
            {"type": "sense", "sense_id": "sense_bat_sport", "language": "en-UK"},
            {"type": "sense", "sense_id": "sense_chauve_souris", "language": "fr-FR"},
            {"type": "sense", "sense_id": "sense_batte", "language": "fr-CA"},
            {
                "type": "translation",
                "translation_id": "tr_animal",
                "from_sense_id": "sense_bat_animal",
                "to_sense_id": "sense_chauve_souris",
                "source": {"source_id": "src_1", "dataset_version": "1.0"}
            },
            {
                "type": "translation",
                "translation_id": "tr_sport",
                "from_sense_id": "sense_bat_sport",
                "to_sense_id": "sense_batte",
                "source": {"source_id": "src_1", "dataset_version": "1.0"}
            }
        ]
        results = self._run_mapper(lines)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["from_language"], "en-US")
        self.assertEqual(results[0]["to_language"], "fr-FR")
        self.assertEqual(results[1]["from_language"], "en-UK")
        self.assertEqual(results[1]["to_language"], "fr-CA")
if __name__ == '__main__':
    unittest.main()
