# DEUTSCH-IMPROVE-07 — language coverage gaps (read-only)

This is a sparse gap report, not a replacement for the authoritative `tools/gha_factory/coverage_audit/check.py` and not permission to publish language packs.

From the public repository root:

```sh
python3 tools/language_coverage/report.py --root . --output-dir "$HOME/deutsch-coverage"
python3 -m unittest discover -s tests/language_coverage -p 'test_*.py' -v
```

Inputs from the same checked-out HEAD: `manifest.json`, `catalog/language_registry.v1.json`, `catalog/content_readiness.v1.json`, `legal/ledger/sources.json`, and `version.json`.

Outputs: `coverage.json` and `coverage.csv`. In the absence of independently validated corpus records, dimension counts remain **UNKNOWN**, not `0`. No directed pair is inferred from its inverse. The optional `--pairs-jsonl` accepts up to 5000 source-target assertions, labels their unverified claim count separately, and never treats it as verified. An explicit approved source in metadata is not confirmation of its actual immutable bytes or legal approval. Reports are advisory even if the CLI exits 0. Run the canonical coverage audit separately before release.
