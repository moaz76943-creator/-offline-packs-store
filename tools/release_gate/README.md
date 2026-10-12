# Public pilot5 release gate

**Current state: BLOCKED_DEPENDENCY. No production packs published.**

This directory contains an offline, standard-library-only release audit. It does **not**
compile, download, sign, upload or publish content. It never accesses private application
sources. Existing `packs/*_universal_v1.pack.gz` and `*_core_a1.pack.gz` remain
legacy files, not verified SQLite v2 production content.

## Run on a checkout (without Actions)

```sh
python3 -m unittest discover -s tools/release_gate -p 'test_*.py' -v
python3 -m compileall -q tools/release_gate
python3 -m json.tool manifest.json >/dev/null
python3 -m json.tool version.json >/dev/null
python3 tools/release_gate/gate.py --repo-root . --output tools/release_gate/local_evidence.json
git diff --check
```

Gate exit **0** means all implemented candidate checks passed; exit **2** means blocked.
The optional output file is a local, machine-readable audit snapshot and must be reviewed
before use. The checked-in release evidence is a dated snapshot, not a future approval.

## Required blockers to resolve upstream

- **Route 02:** verified public safety scanner run and scoped public evidence.
- **Route 03:** approved, canonical 100-language registry; preserve stable IDs.
- **Route 05:** dataset-specific licensing ledger, original artifact bytes and SHA-256,
  attribution obligations, legal notices and approved daily publication candidates.
- **Route 06:** approved public lexical and SQLite v2 mapping.
- **Route 07:** canonical deterministic compiler with all **three** approved consumer
  envelope files: `content/content.json`, `content/content.sqlite`,
  `metadata/pack.json`.
- **Route 08:** real accepted German, Arabic, English, Spanish and French corpus
  from approved redistributable sources; **synthetic test fixtures do not qualify**.
- **Consumer:** independently approved *neutral* installation fixture and compatibility
  evidence; never export private downloader implementation.

After all dependencies pass, record reviewed public route evidence in
`route_approvals.json` under this directory. Each route `02`, `03`, `05`,
`06`, `07`, `08`, and `consumer` must have `status: APPROVED`,
a repository-local `evidence_path` and the actual evidence file `sha256`.
File presence alone is never sufficient. Release approval also requires an independently
reviewed human decision; a green script alone is not legal certification.

The gate validates any descriptors it finds in `manifest.packs`: exact archive
location and SHA-256, semver, gzip envelope size limits, base64 member paths, SQLite
v2 integrity and foreign-key checks, real row counts, FTS5 MATCH queries, and content
hashes. `version.packs` must point to exact committed paths. Before publication, add
tests for approved consumer installation, the accepted licence/attribution notices,
an immutable-asset version migration and rollback fixtures. Until then the release
remains **BLOCKED_DEPENDENCY**; the present gate is a candidate guard, not a claim of
full release certification.

The 100 existing language identities and legacy download metadata are retained in
`manifest.languages` as **inactive, unverified legacy references**. `version.json`
no longer advertises the 100 nonexistent `*_master.pack.gz` URLs. The historical
`latest_version` string is preserved only for old clients; `latest_verified_version`
is null and `release_status` is BLOCKED_DEPENDENCY.
