import unittest
import json
from pathlib import Path
from standards.directed_pairs.validate import validate, DirectedPairContractError

FIXTURES_DIR = Path(__file__).parent / "fixtures"

class TestFixtures(unittest.TestCase):
    def _validate_fixture(self, filename, should_pass):
        with open(FIXTURES_DIR / filename, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if should_pass:
            self.assertEqual(validate(doc), doc)
        else:
            with self.assertRaises(DirectedPairContractError):
                validate(doc)

    def test_polysemous(self):
        self._validate_fixture("polysemous.json", True)

    def test_homographs(self):
        self._validate_fixture("homographs.json", True)

    def test_regional_variants(self):
        self._validate_fixture("regional_variants.json", True)

    def test_reverse_pairs(self):
        self._validate_fixture("reverse_pairs.json", True)

    def test_invalid_same_language(self):
        self._validate_fixture("invalid_same_language.json", False)

    def test_invalid_missing_sense(self):
        self._validate_fixture("invalid_missing_sense.json", False)

if __name__ == "__main__":
    unittest.main()
