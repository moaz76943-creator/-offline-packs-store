import unittest
from standards.morphology.validate import validate, MorphologyContractError

class TestMorphologyValidator(unittest.TestCase):
    def setUp(self):
        self.base_source = {
            "source_id": "src1",
            "origin_url": "https://example.com/data",
            "publisher": "Example Pub",
            "dataset_version": "1.0",
            "retrieval_id": "ret1",
            "license_id": "CC0-1.0",
            "record_locator": "loc1",
            "publication_approved": True,
            "fixture_only": False
        }

    def test_valid_agglutinative_turkish(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc1",
            "forms": [
                {
                    "form_id": "frm1",
                    "lemma_id": "lem1",
                    "form": "evlerimde",
                    "language": "tur",
                    "analyses": [
                        {
                            "features": {"number": "plural", "case": "locative", "person": "1st_singular"},
                            "morphemes": ["ev", "ler", "im", "de"]
                        }
                    ],
                    "source": self.base_source
                }
            ]
        }
        self.assertEqual(validate(doc), doc)

    def test_valid_semitic_root_pattern_arabic(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc2",
            "forms": [
                {
                    "form_id": "frm2",
                    "lemma_id": "lem2",
                    "form": "مكتوب",
                    "language": "ara",
                    "analyses": [
                        {
                            "root": "k-t-b",
                            "pattern": "ma12u3",
                            "features": {"participle": "passive"}
                        }
                    ],
                    "source": self.base_source
                }
            ]
        }
        self.assertEqual(validate(doc), doc)

    def test_valid_analytic_mandarin(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc3",
            "forms": [
                {
                    "form_id": "frm3",
                    "lemma_id": "lem3",
                    "form": "吃了",
                    "language": "cmn",
                    "analyses": [
                        {
                            "analytic_components": ["cmp1", "cmp2"],
                            "features": {"aspect": "perfective"}
                        }
                    ],
                    "source": self.base_source
                }
            ]
        }
        self.assertEqual(validate(doc), doc)

    def test_ambiguous_form(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc4",
            "forms": [
                {
                    "form_id": "frm4",
                    "lemma_id": "lem4",
                    "form": "bear",
                    "language": "eng",
                    "analyses": [
                        {"features": {"pos": "noun", "number": "singular"}},
                        {"features": {"pos": "verb", "tense": "present"}}
                    ],
                    "source": self.base_source
                }
            ]
        }
        self.assertEqual(validate(doc), doc)

    def test_invalid_unsupported_feature_mandarin(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc5",
            "forms": [
                {
                    "form_id": "frm5",
                    "lemma_id": "lem5",
                    "form": "吃",
                    "language": "cmn",
                    "analyses": [
                        {
                            "features": {"tense": "past"}
                        }
                    ],
                    "source": self.base_source
                }
            ]
        }
        with self.assertRaisesRegex(MorphologyContractError, 'unsupported feature "tense" for language "cmn"'):
            validate(doc)

    def test_invalid_missing_source(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc6",
            "forms": [
                {
                    "form_id": "frm6",
                    "lemma_id": "lem6",
                    "form": "test",
                    "language": "eng",
                    "analyses": [{"features": {"number": "singular"}}]
                }
            ]
        }
        with self.assertRaises(MorphologyContractError):
            validate(doc)

    def test_invalid_duplicate_form_id(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc7",
            "forms": [
                {
                    "form_id": "frm7",
                    "lemma_id": "lem7",
                    "form": "test",
                    "language": "eng",
                    "analyses": [{"features": {"number": "singular"}}],
                    "source": self.base_source
                },
                {
                    "form_id": "frm7",
                    "lemma_id": "lem8",
                    "form": "test2",
                    "language": "eng",
                    "analyses": [{"features": {"number": "singular"}}],
                    "source": self.base_source
                }
            ]
        }
        with self.assertRaisesRegex(MorphologyContractError, 'duplicate form ID: frm7'):
            validate(doc)

    def test_invalid_unknown_lemma(self):
        doc = {
            "contract_version": "1.0.0",
            "document_id": "doc8",
            "forms": [
                {
                    "form_id": "frm8",
                    "lemma_id": "lem99",
                    "form": "test",
                    "language": "eng",
                    "analyses": [{"features": {"number": "singular"}}],
                    "source": self.base_source
                }
            ]
        }
        with self.assertRaisesRegex(MorphologyContractError, 'form references unknown lemma: lem99'):
            validate(doc, lemmas={"lem1", "lem2"})

if __name__ == '__main__':
    unittest.main()
