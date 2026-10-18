"""The shared synthetic source stays aligned with the ledger schema and admission."""
import json
import tempfile
import unittest
from pathlib import Path

from legal.ledger.admission import evaluate
from legal.ledger.synthetic import missing_required_fields, synthetic_source

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "legal" / "ledger" / "schema.json").read_text(encoding="utf-8"))


class SyntheticLedgerContractTest(unittest.TestCase):
    def test_fixture_covers_every_required_schema_field_and_author(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_source(tmp)
        self.assertEqual(missing_required_fields(source, SCHEMA), [])
        properties = SCHEMA["$defs"]["source"]["properties"]
        self.assertIn("author", properties)
        self.assertEqual(source["author"], "synthetic-fixture")
        self.assertTrue(set(source) <= set(properties))

    def test_fixture_passes_current_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_source(tmp)
            errors = evaluate(
                {"schema_version": "1.0.0", "sources": [source]},
                {"languages": [], "packs": []},
                [],
                tmp,
            )
        self.assertEqual(errors, [])

    def test_search_qa_reviewed_source_reuses_the_shared_fixture(self):
        from tests.gha_factory.search_qa.test_audit import SearchAuditTests

        with tempfile.TemporaryDirectory() as tmp:
            case = SearchAuditTests()
            case.root = Path(tmp)
            source = case.reviewed_source()
            errors = evaluate(
                {"schema_version": "1.0.0", "sources": [source]},
                {"languages": [], "packs": []},
                [],
                tmp,
            )
        self.assertEqual(errors, [])
        self.assertEqual(source["author"], "synthetic-fixture")
        self.assertEqual(source["source_id"], "fixture-source")

    def test_dropping_a_required_field_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = synthetic_source(tmp)
        source.pop("publisher")
        self.assertEqual(missing_required_fields(source, SCHEMA), ["publisher"])


if __name__ == "__main__":
    unittest.main()
