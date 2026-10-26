import unittest
from tools.factory_extensions.pronunciation_scale.adapters import from_pr97, inspect_pr99
from tools.factory_extensions.pronunciation_scale.factory import AuditError


class AdapterTests(unittest.TestCase):
    def test_pr97_identity_and_variant_are_stable_and_not_audio(self):
        rec = {"record_id": "rec_de_01", "lexeme_id": "lex_de_01", "sense_id": "sense_de_01",
               "language": "de", "script": "Latn", "locale": "de-DE",
               "offline_voice_status": "device_installed",
               "pronunciations": [{"notation": "ipa", "value": "ˈhaʊs", "stress": "first", "dialect": "standard",
                  "source": {"source_id": "src_de", "publisher": "Publisher", "dataset_version": "v1",
                             "record_locator": "row/10", "license_id": "CC0-1.0", "publication_approved": True}}]}
        doc = from_pr97({"registry_version": "1.0.0", "records": [rec]})
        self.assertEqual(doc["records"][0]["reading"]["value"], "ˈhaʊs")
        self.assertEqual(doc["records"][0]["language_tag"], "de-DE")
        self.assertEqual(doc["records"][0]["audio"], [])
        self.assertNotIn("offline_voice_status", str(doc))
        self.assertEqual(from_pr97({"registry_version": "1.0.0", "records": [rec]})["records"], doc["records"])

    def test_pr97_missing_source_locator_cannot_promote(self):
        rec = {"record_id":"rec1", "lexeme_id":"lex1", "language":"de", "script":"Latn",
               "source": {"publication_approved":True},
               "pronunciations": [{"notation":"ipa", "value":"ha", "source": {"source_id":"x"}}]}
        with self.assertRaises(AuditError):
            from_pr97({"registry_version":"1.0.0", "records":[rec]})

    def test_pr99_unenriched_audio_never_auto_admitted(self):
        report = inspect_pr99({"assets":[{"record_id":"a1", "audio_path":"sound.wav", "sha256":"0"*64,
                                           "source":{"source_id":"x"}}]})
        self.assertEqual(report["admitted"], [])
        self.assertEqual(report["quarantined"][0]["reason"], "independent_audio_rights_and_speaker_review_required")


if __name__ == "__main__":
    unittest.main()
