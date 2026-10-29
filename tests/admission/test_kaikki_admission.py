import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.admission.legal_admission_validator import validate_source_entry

class TestKaikkiAdmission(unittest.TestCase):
    def test_sources_ledger_compliance(self):
        ledger_path = os.path.join(os.path.dirname(__file__), "../../legal/ledger/sources.json")
        with open(ledger_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sources = data.get("approved_sources", [])
        self.assertTrue(len(sources) > 0)

        for source in sources:
            valid, errors = validate_source_entry(source)
            self.assertTrue(valid, f"Source {source.get('source_id')} failed validation: {errors}")

if __name__ == '__main__':
    unittest.main()
