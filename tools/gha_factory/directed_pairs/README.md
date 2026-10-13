# GHA directed-pair QA (candidate-only)

This independent Python stdlib validator consumes **unmodified GHA-05 candidate
JSONL** and verifies each claimed Tatoeba edge against SHA-256 pinned original
`sentences_detailed` (6 TSV columns), `links` (2 TSV columns), and
`sentences_cc0` (4 TSV columns). It checks both explicit link directions,
original identity/language/text/author, exact CC0 licensing claims, stable IDs,
and Unicode integrity. The official sentences_CC0 fourth column is last-modified date, NOT author; licensing matches id/language/text, while username attribution is independently checked against sentences_detailed. It uses disk-backed SQLite for source/link/duplicate
indexes, with bounded JSONL/TSV reads and at most 100,000 pairs per job.
No transitive inference; German→English + English→Arabic never asserts German→Arabic.

Example invocation with *already-acquired, independently reviewed* files:

```bash
python3 -m tools.gha_factory.directed_pairs.validator \
  --detailed /verified/detailed.tsv --detailed-sha256 "$DETAILED_SHA" \
  --links /verified/links.tsv --links-sha256 "$LINKS_SHA" \
  --cc0 /verified/cc0.tsv --cc0-sha256 "$CC0_SHA" \
  --candidates /verified/candidates.jsonl --candidates-sha256 "$PAIR_SHA" \
  --catalog manifest.json --out /tmp/direct-pair-qa.json
```

For any language beyond the five pilot ISO-639-3 mappings, a reviewed
`--mapping` JSON must declare the complete mapping including pilot entries.
No language code is guessed from script appearance.

**Important:** The output is always `QA_ONLY_REVIEW_REQUIRED`,
`publication_approved=false`, `semantic_equivalence_approved=false`, and
`source_rights_approved=false`. Tatoeba raw links prove only that source links
exist, not final correctness, direction-specific semantics, independent source
rights admission or editorial review. Route 05/GHA-01 approvals and GHA-02
queue integration are external prerequisites. No production data is acquired,
downloaded, modified or published by this module.

QA using synthetic fixtures:

```bash
python3 -m unittest discover -s tests/gha_factory/directed_pairs -p 'test_*.py' -v
```

The dedicated GitHub workflow runs these tests only, on public standard Ubuntu,
never requests write permission, caches, or artifacts. It does not spawn
continuous or paid corpus processing.
