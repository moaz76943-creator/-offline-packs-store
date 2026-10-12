# Morphology capability and evidence v1

This directory contains **capability contracts**, not generated conjugation databases. The public `manifest.json` (100 entries at base commit `bb15e9f02b216bbcb62a254d4a5bd695d405e9d5`) is the authoritative list of product language IDs; the engine reads it at runtime and requires exactly 100 unique codes. A future canonical registry may be integrated explicitly after its schema stabilizes. `family`, `name`, native name and public direction are copied from that input unchanged; do not reinterpret `direction` as a universal script direction.

`feature_overrides.json` defines 25 **independent** dimensions, including grammatical gender vs. noun class, number and case, verbal TAM/voice/person, root-pattern/nonconcatenative morphology, affix/clitic/compound, harmony and agglutinative order, tones and analytic features, classifiers, honorifics, orthography and segmentation. Each dimension is `supported`, `not_applicable`, or `unknown`. Language-level overrides are explicit; family is metadata **never an implicit inference rule**. `contracts` describe future family-specific implementations, not a generator. Any unclaimed feature remains `unknown`.

`attested_forms.jsonl` contains a deliberately small set of independently checked facts with immutable language-scoped lemma and sense identifiers, original Unicode spelling, feature tags, processes, source identifiers and evidence dates. `sources.json` documents exact reference URLs and restrictions. Its content is **not** a warranty of wholesale redistribution rights for dictionary entries. No source pages, proprietary paradigms, analyzer models or private application code are bundled. Refer to repository licensing review before expanding datasets.

The engine **only retrieves exact attested forms**. It does not make forms by trimming endings, guessing plurals, assigning Arabic broken plural patterns, manufacturing auxiliary compounds, or applying Turkic harmony without lexical evidence. An unattested lookup always yields `unknown`, including requests for plausible yet absent forms. Query identity always includes language and optional sense; callers may not silently mix grammars. A streaming JSONL scan and capped LRU caches keep memory bounded as evidence grows, at the cost of a sequential scan on cache misses.

Run from repository root:

```shell
python3 -m unittest discover -s tools/morphology_profiles -p 'test_*.py' -v
python3 -m compileall -q tools/morphology_profiles
python3 -m unittest discover -s standards/morphology -p 'test_*.py' -v
python3 tools/morphology_profiles/engine.py --language ar
```

## Extension protocol

1. Confirm registered stable language code and script/locale variant using the public language registry; never assume family conventions apply to every member.
2. Add explicit, independently justified capabilities to the rulebook; leave unknown dimensions `unknown`.
3. Add single-lemma source references with author/publisher, exact URL, reuse restrictions and evidence version.
4. Add a handful of attested forms with stable `lemma_id`, `sense_id` and exact Unicode; test negative/homograph cases before growing coverage.
5. Require verified data and dedicated tests before introducing family-specific productive generation. `analysis_status=pilot_attested` signals **sample coverage only**, not a complete analyzer.
