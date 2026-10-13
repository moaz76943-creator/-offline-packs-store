# GHA multilingual sentence and exercise factory (independent scope)

Offline Python standard-library-only parser and candidate producer. It does not publish
packs or download audio. The canonical source contracts remain in
`tools/source_examples/sentence.schema.json`, `standards/lexical/`,
`standards/morphology/`, `legal/ledger/sources.json` and
`catalog/language_registry.v1.json`. Existing Route 06/07/08 outputs are
read-only; the present worker does **not** assert SQLite v2 production readiness.

## Immutable input

Supply extracted, *real* Tatoeba TSV archives from the official weekly export
(https://tatoeba.org/en/downloads): `sentences_detailed` (6 tab fields),
`sentences_cc0` (4 tab fields), `links` (2 tab fields), and optionally
`sentences_with_audio` (5 tab fields). Never synthesize missing text, author,
ID, link, license or audio. Store uncompressed immutable TSVs outside the repository
under a local read-only snapshot directory. Job JSON format:

```json
{
  "source_id":"tatoeba",
  "snapshots":{
    "detailed":{"path":"detailed.tsv","sha256":"<64-hex SHA-256>"},
    "cc0":{"path":"cc0.tsv","sha256":"<64-hex SHA-256>"},
    "links":{"path":"links.tsv","sha256":"<64-hex SHA-256>"}
  },
  "language_map":{"jpn":"ja","zho":"zh"}
}
```

The `language_map` is an explicit reviewed identity mapping into the canonical
100-language catalog; five known Tatoeba ISO-639-3 codes are built in:
`deu/de`, `ara/ar`, `eng/en`, `spa/es`, `fra/fr`. All others must be
supplied explicitly; aliases are not guessed. A language/script heuristic can reject
obvious mismatches but cannot establish English-vs-German or any other same-script
identity: **independent source-language verification remains required**.

Run from repository root:

```sh
python3 -m tools.gha_factory.examples.factory \
  --workspace /absolute/immutable/snapshot_directory \
  --config /tmp/examples-job.json --catalog manifest.json \
  --ledger legal/ledger/sources.json --out /tmp/examples-candidates \
  --partition-size 5000 --deadline-seconds 900
python3 -m unittest discover -s tests/gha_factory/examples -p 'test_*.py' -v
```

All input snapshots must have exact SHA-256 matches. SQLite is a disk-backed,
bounded-memory index; records are streamed, direct reciprocal links verified,
and Arabic source/target identities are preserved. Sorted candidate partitions
have deterministic names and IDs, with source hashes and a checkpoint in
`report.json`. Never interpret Tatoeba links as manually reviewed semantic
equivalence or infer indirect links via English.

A genuine sentence's default Tatoeba license is **CC BY 2.0 FR**, which is not
currently supported by the Route 05 ledger schema. CC0 must be verified against
the **exact** CC0 export row (ID, language, text); source-level Route 05 rights
review and snapshot proof are still required. Text and individual audio rights
are separate. Unlicensed, missing-license, non-commercial, or unsupported audio
is withheld; no audio files are fetched. Recording metadata is never a license grant.

Cloze building is only from authenticated source text with reviewer-attested
exact character offsets, an approved canonical lexical sense, morphology-matched
attested answer/distractors and a reviewed unambiguity decision. No generated
sentences, machine translation, guessed grammar, guessed distractors or inferred
CEFR are permitted. The helper `make_cloze` fails closed. The production path is
blocked until real source, editor, sense and morphology approvals exist; the
current TSV ingestion intentionally admits **zero exercises**.

**Dependencies:** Route GHA-01 source/rights approval is absent while the public
ledger is empty. Route GHA-02 dispatcher exists, but its current task allowlist
supports `registry_validate` and `admission_partition_verify`, **not**
`examples_ingest`. Do not create a fake queue task or bypass GHA-02.
The separate `gha_examples_worker.yml` provides manually triggered tests only.
No job is dispatched by this factory; a run ID is never fabricated.
