import json
import unittest
from pathlib import Path
from validate import validate, verify_compatible, DirectedPairContractError

class TestDirectedPairValidator(unittest.TestCase):
    def test_valid_document(self):
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        self.assertEqual(validate(document), document)

    def test_duplicate_translation_id(self):
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                },
                {
                    "translation_id": "tra.t1",
                    "source_language": "es",
                    "target_language": "en",
                    "source_sense_id": "sen.s2",
                    "target_sense_id": "sen.s1",
                    "translation": "hello",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as ctx:
            validate(document)
        self.assertIn("duplicate translation ID", str(ctx.exception))

    def test_same_source_target_language(self):
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "en",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hello",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as ctx:
            validate(document)
        self.assertIn("source and target language cannot be the same", str(ctx.exception))

    def test_missing_required_fields(self):
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    # missing source_sense_id
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as ctx:
            validate(document)
        self.assertIn("JSON Schema violation", str(ctx.exception))

    def test_verify_compatible_success(self):
        prev = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        updated = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola!", # updated translation
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.1",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        self.assertTrue(verify_compatible(prev, updated))

    def test_verify_compatible_failure_removed(self):
        prev = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        updated = {
            "schema_version": "1.0.0",
            "translations": []
        }
        with self.assertRaises(DirectedPairContractError) as ctx:
            verify_compatible(prev, updated)
        self.assertIn("breaking removal of tra.t1", str(ctx.exception))

    def test_verify_compatible_failure_reassigned(self):
        prev = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "hola",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        updated = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.t1",
                    "source_language": "en",
                    "target_language": "fr", # changed
                    "source_sense_id": "sen.s1",
                    "target_sense_id": "sen.s2",
                    "translation": "salut",
                    "type": "literal",
                    "source": {
                        "source_id": "src.s1",
                        "publisher": "pub1",
                        "version": "1.0",
                        "license_id": "CC-BY-4.0"
                    }
                }
            ]
        }
        with self.assertRaises(DirectedPairContractError) as ctx:
            verify_compatible(prev, updated)
        self.assertIn("stable identity reassignment: tra.t1", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
