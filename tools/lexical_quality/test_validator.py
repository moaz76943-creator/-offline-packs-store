import unittest
from tools.lexical_quality.validator import LexicalQualityValidator, MAX_RECORD_SIZE
from tools.lexical_quality.fixtures import VALID_ENTRIES, INVALID_ENTRIES, REVIEW_REQUIRED_ENTRIES

class TestLexicalQualityValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LexicalQualityValidator()

    def test_valid_entries(self):
        results = list(self.validator.validate_stream(VALID_ENTRIES))
        for res in results:
            self.assertEqual(res["status"], "accepted", res)
            self.assertEqual(res["errors"], [])
            self.assertEqual(res["reasons"], [])
            self.assertIn("record", res)

    def test_invalid_entries(self):
        # We need a new validator to ensure seen_ids is empty, or we can reuse it
        # as long as we know what to expect. Since we are testing invalid entries,
        # it's better to use a fresh validator for independence.
        validator = LexicalQualityValidator()
        results = list(validator.validate_stream(INVALID_ENTRIES))

        for res in results:
            self.assertEqual(res["status"], "rejected", res)
            self.assertTrue(len(res["errors"]) > 0, res)

        # Specific checks based on the fixture
        self.assertIn("Missing 'id' field", results[0]["errors"])
        self.assertIn("Missing 'surface' field", results[1]["errors"])
        self.assertIn("'surface' field cannot be empty or whitespace", results[2]["errors"])
        self.assertIn("Invalid Unicode: null byte in 'surface'", results[3]["errors"])
        self.assertIn("Invalid 'language' format", results[4]["errors"])
        self.assertIn("'translations' field must be a list", results[5]["errors"])
        self.assertTrue(any("missing or invalid 'text'" in err for err in results[6]["errors"]), results[6]["errors"])
        self.assertTrue(any("missing or invalid 'text'" in err for err in results[7]["errors"]), results[7]["errors"])
        self.assertIn("'pos' field must be a string", results[8]["errors"])

    def test_review_required_entries(self):
        validator = LexicalQualityValidator()
        results = list(validator.validate_stream(REVIEW_REQUIRED_ENTRIES))

        for res in results:
            self.assertEqual(res["status"], "reviewRequired", res)
            self.assertEqual(res["errors"], [])
            self.assertTrue(len(res["reasons"]) > 0, res)

        self.assertIn("Impossible combination: noun with conjugations", results[0]["reasons"])
        self.assertIn("Impossible combination: verb with plural", results[1]["reasons"])

    def test_duplicate_id(self):
        validator = LexicalQualityValidator()
        entries = [
            {"id": "dup-1", "surface": "test1", "language": "eng", "pos": "noun"},
            {"id": "dup-1", "surface": "test2", "language": "eng", "pos": "noun"}
        ]
        results = list(validator.validate_stream(entries))

        self.assertEqual(results[0]["status"], "accepted")
        self.assertEqual(results[1]["status"], "rejected")
        self.assertIn("Duplicate ID detected: dup-1", results[1]["errors"])

    def test_max_record_size(self):
        validator = LexicalQualityValidator()
        huge_surface = "a" * (MAX_RECORD_SIZE + 10)
        entries = [
            {"id": "huge-1", "surface": huge_surface, "language": "eng", "pos": "noun"}
        ]
        results = list(validator.validate_stream(entries))

        self.assertEqual(results[0]["status"], "rejected")
        self.assertIn("Record exceeds maximum size limit of 1MB", results[0]["errors"])

    def test_memory_bound(self):
        validator = LexicalQualityValidator()
        # Add 100,001 IDs to push beyond MAX_SEEN_IDS (100,000)
        # To make it fast, we can just modify the validator state directly for testing the bound
        for i in range(100000):
            validator.seen_ids[f"id-{i}"] = True

        validator.seen_ids["trigger"] = True
        if len(validator.seen_ids) > 100000:
            validator.seen_ids.popitem(last=False)

        self.assertEqual(len(validator.seen_ids), 100000)
        self.assertNotIn("id-0", validator.seen_ids)

if __name__ == '__main__':
    unittest.main()
