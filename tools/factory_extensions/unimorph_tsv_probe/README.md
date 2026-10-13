# UniMorph TSV bounded syntax probe (non-production)

An isolated, stdlib-only *inspection* aid for candidate UniMorph 3-column TSV snapshots.
It does not admit a source, verify any inflection, assert source license rights,
create lexical IDs, publish content, or enqueue a job. Fixtures are synthetic.

- Requires a **real independently verified SHA-256** of a local regular file.
- Reads a bounded 1-based line partition (at most 10,000 rows) with strict UTF-8.
- Records candidate, rejected, duplicate and source-row counts, with bounded
  per-partition duplicate tracking and a deterministic fingerprint.
- Rejects malformed TSV, invalid Unicode control characters, unsupported tag
  syntax, truncated partitions, unsafe symlinks and mismatched file hashes.
- ISO-639-3 is explicit (`eng` for this pilot); **not** an app's `en` identity.
- Morphological tags are syntactically screened, **not** semantically validated.
- Does not ingest or propagate private data, audio, translations, CEFR or source URLs.

**Legal block:** current Route05 `legal/ledger/sources.json` has no approved
sources; UniMorph English rights, version and attribution are `REVIEW_REQUIRED`.
CC BY-SA 3.0 is not currently supported by Route05 admission and must not be
relabelled CC BY-SA 4.0 or CC0. No production dispatch or publication is allowed.

Run tests without dependencies:

```sh
python3 -m unittest discover -s tests/factory_extensions/unimorph_tsv_probe -v
```

Any later integration requires explicit Route05/08 ownership, reviewed source
license evidence, exact artifact and evidence hashes, canonical language mapping,
real corpus-derived tests, and queue/worker integration with durable receipts.
