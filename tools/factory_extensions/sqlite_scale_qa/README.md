# SQLite v2 scale QA (read-only adapter)

This extension **does not compile a competing format, sign, publish, or promote**. It delegates archive security, three-file envelope, schema, FTS integrity, language registry, rights and strict JSON checks to `tools.gha_factory.pack_conformance.check`, `tools.gha_factory.release.candidate`, and `tools.pack_v2.pipeline` (merged PR #76 strict conformance; PR #66 security fuzzing is still open and is not treated as merged). Use the canonical compiler only.

Audit without modifying packs or manifests:

```sh
python3 -m tools.factory_extensions.sqlite_scale_qa.verify --root .
```

For a genuinely approved source JSON and already compiled archive, supply **all** of `--archive`, `--language`, `--sha256`, `--source`, and `--probes`; the latter two must be immutable files within the repository, rights-approved where applicable. The adapter compares the entire SQLite lexical row payload collection and stable ID sets with the exact source (including directed translations), checks exact result sets for attested script-specific queries, verifies optional grammar sidecar rows against the canonical SQLite grammar table, then compiles twice in isolated temporary directories. A different SHA blocks release. It never writes `packs/`, `manifest.json`, `version.json`, or Legacy/LKG.

Search evidence is an independently reviewed JSON file, not an automatically generated expectation:

```json
{
  "contract_version": "1.0.0",
  "cases": [
    {
      "language": "de", "script": "Latn", "source_id": "approved.source.id",
      "query": "Haus", "mode": "fts_phrase", "expected_ids": ["attested.lexeme.id"]
    }
  ]
}
```

Allowed modes are `fts_phrase` (actual SQLite FTS5 query) and `exact_surface` (byte-preserving direct SQL equality). Every target-language script in the source requires its own independently attested probe. An exact-surface pass is **not** evidence that FTS word segmentation is good; exact search and FTS results are reported separately. Arabic diacritic-optional lookup, CJK word breaking, Thai dictionary segmentation, Hangul normalization, and Indic grapheme/word processing **must not be claimed** until the actual runtime/index supports language-specific attested queries that pass. Never infer such equivalences from `unicode61` or normalize the stored original text destructively.

The adapter reports counts from canonical inspection, measured archive/SQLite byte sizes, overall verification time, per-query measured latency, and two full compile times. The canonical compiler does not expose an independent *indexing-only* timer; therefore indexing time is **not measured** separately. Fixture tests only prove failure handling, never linguistic coverage or rights. Approval/signature, Route 05 source licenses, release candidate QA, on-device verification, and non-destructive promotion remain independent required gates. No production compile shard can run while the public approved-source ledger is empty; therefore no genuine Task ID, Run ID, or production checkpoint is claimed.

The search-evidence workload is capped at 128 cases, 256 expected IDs per case and 10 seconds per SQLite query. Actual production linguistics and indexing-only time remain NOT_VERIFIED/NOT_MEASURED. Hosted regression checks must execute before any code-only PR merge; this QA adapter must never itself authorize publication.
