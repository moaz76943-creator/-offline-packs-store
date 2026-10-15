import json
import unittest
from validate import validate

class TestDirectedPairFixtures(unittest.TestCase):
    def test_polysemous_word(self):
        # Example: 'bank' (financial institution vs river bank)
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.bank.fin",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.bank.fin",
                    "target_sense_id": "sen.banco",
                    "translation": "banco",
                    "type": "literal",
                    "context": "financial institution",
                    "domain": "finance",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                },
                {
                    "translation_id": "tra.bank.river",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.bank.river",
                    "target_sense_id": "sen.orilla",
                    "translation": "orilla",
                    "type": "literal",
                    "context": "side of a river",
                    "domain": "geography",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                }
            ]
        }
        self.assertEqual(validate(document), document)

    def test_regional_variant(self):
        # Example: 'car' (coche in Spain, carro in Latin America)
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.car.es",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.car",
                    "target_sense_id": "sen.coche",
                    "translation": "coche",
                    "type": "literal",
                    "context": "used in Spain",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                },
                {
                    "translation_id": "tra.car.la",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.car",
                    "target_sense_id": "sen.carro",
                    "translation": "carro",
                    "type": "literal",
                    "context": "used in Latin America",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                }
            ]
        }
        self.assertEqual(validate(document), document)

    def test_reverse_pair_distinction(self):
        # Example: 'know' to 'saber' vs 'conocer'
        document = {
            "schema_version": "1.0.0",
            "translations": [
                {
                    "translation_id": "tra.know.saber",
                    "source_language": "en",
                    "target_language": "es",
                    "source_sense_id": "sen.know.fact",
                    "target_sense_id": "sen.saber",
                    "translation": "saber",
                    "type": "literal",
                    "context": "know a fact",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                },
                {
                    "translation_id": "tra.saber.know",
                    "source_language": "es",
                    "target_language": "en",
                    "source_sense_id": "sen.saber",
                    "target_sense_id": "sen.know.fact",
                    "translation": "know",
                    "type": "literal",
                    "context": "know a fact",
                    "source": {
                        "source_id": "src.1",
                        "publisher": "test",
                        "version": "1",
                        "license_id": "CC0"
                    }
                }
            ]
        }
        self.assertEqual(validate(document), document)

if __name__ == '__main__':
    unittest.main()
