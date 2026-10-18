# Independently sourced diverse-language typology and candidate review

This isolated read-only extension covers 14 **distinct canonical IDs**:
`sw`, `zu`, `xh`, `rw`, `sn`, `yo`, `ig`, `ha`, `so`, `mg`,
`id`, `ms`, `tl`, `am`. A language is never replaced by a related
majority language; `fil` is not treated as a verified synonym for `tl`.
The script/variety and original UTF-8 spelling are preserved.

## Reviewed structural evidence is not a dictionary

`evidence.json` contains **7** distinct, attributed WALS datapoints for
7 languages: Yoruba, Igbo and Hausa tone classification; Indonesian and
Tagalog reduplication classification; Swahili and Zulu WALS **controller
gender-class counts**. The last category reflects Corbett's typological
agreement-class analysis: **not German der/die/das gender, not an attested
list of Bantu noun-class prefixes, and not a productive class-concord
generator**. These classifications are not word-level tone marks, a grammar
generator, a speech asset, or lexeme redistribution approval.

All 14 IDs are represented in independent `RESEARCH_FOCUS` entries.
The other seven identities have **zero verified structural facts** here;
the canonical registry's morphology is explicitly provisional. For each
language, spelling, tone, noun classes, concord, verbal extensions, affixes,
focus/voice and reduplication require independently sourced **per-form**
evidence. No morphology is imported from a neighboring language.

## Canonical legal proof and language-specific binding

The source registry has the **real Route05 shape**, not the older imagined
`source.license` string, `review.approved_by`, `source.rights_url` or
`source.languages` fields. It is validated using the actual
`legal/ledger/admission.py` gate, which checks immutable source and
licence proof bytes, declared CC/GFDL/public-domain restrictions, publisher,
dataset version and publicly evidenced human review.

`source_bindings.json` is an **empty**, independent, explicitly reviewed
source-to-language-and-variety attestation manifest. A future binding must
contain exactly these keys:

```json
{
  "source_id": "source-id-from-Route05",
  "language_id": "yo",
  "variant": "yo-Latn",
  "proof_path": "a-repository-relative-language-identity-proof-file",
  "proof_sha256": "64-lowercase-hex-digest",
  "review": {
    "reviewer": "reviewed-identity",
    "decision_url": "https://example.org/an-external-review-decision"
  }
}
```

This is an illustrative **schema shape, not an approved example**.
Its SHA-bound local proof and the Route05 source evidence are required,
and the language and script/variety must be linked to that actual source.
Neither a supplied ISO code nor a contributor's unverified consent string
is a substitute for that proof. For shared/community lexical submissions,
an independent consent/rights audit remains required before release.

Pending PRs #88 (intake), #93 (contributor rights) and #94 (community
review) own those pipelines. Do not merge their code, declare a separate
community approval state machine, or promote a candidate into production.
`source_bindings.json` stays empty until independently approved.

## Attested linguistic annotations (no form generation)

Each JSONL candidate has the existing required string keys
`record_id, language_id, lemma, meaning, variant, source_id, publisher,
community, speaker_consent_ref, license, rights_url`, with one optional
`annotation` object containing **exactly** `feature, label, attested_form,
locator`. All four annotation members are nonempty strings and the
attested form is copied verbatim from the source; the locator must resolve
to a reviewed, immutable source. The `feature` field represents a
*request to review a claim*, not a verified grammar capability.

Syntactic review categories are language fenced:
- Bantu class IDs, concord and verbal extensions for `sw, zu, xh, rw, sn`.
- `yo, ig, ha` tone and source-marked orthography, with diacritics never
  inferred from unmarked text.
- `tl, mg` source-specific focus/voice; `id, ms, tl, mg` reduplication.
- Language-scoped affixation and Somali/Amharic inflection, subject to evidence.

Unsupported feature/language pairs, invented source rights, dubious variety,
wrong Unicode types, missing claim locators, conflicts in normalized spellings
and divergent record identities generate bounded **review_queue** reasons.
NFC/casefold are comparison-only, never an output rewrite or silent
normalization. Untrusted speaker names/text are not included in the queue.

## Sparse-source discovery (per-language, no acquisition shortcut)

1. Resolve the **canonical product ID** and variety in the public registry.
   Research Glottolog language bibliography and local native-language
   nomenclature, without treating nearby languages or varieties as aliases.
2. Locate a named, attributable community/publisher grammar or lexicon.
   Use WALS for independently cited typological questions; a WALS category
   is not a transferable lemma or an orthographic/conjugation generator.
3. Identify the actual downloadable snapshot, immutable dataset version,
   publisher licence, reuse scope, precise attribution, and whether community
   participation or individual speaker recording rights are implicated.
4. Route an immutable snapshot and separate licence evidence through
   Route05, then independently review a source-language-variety binding.
   Record rights **and** community consent where applicable; no automatic approval.
5. Review only source-located attested forms in 500-line shards, recording
   `next_line`, per-language candidate/blocked counts and line-numbered
   conflict reasons; audit cross-shard duplicate IDs/meanings independently.
6. Integrate contribution intake only when PRs #88/#93/#94 are reviewed
   and do not publish without separate official release admission.

Run from the public checkout:

```sh
python3 -m unittest discover -s tests/linguistic_extensions/diverse_languages -p 'test_*.py' -v
python3 tools/linguistic_extensions/diverse_languages/audit.py --language sw
python3 tools/linguistic_extensions/diverse_languages/audit.py
python3 tools/linguistic_extensions/diverse_languages/audit.py --input local-candidates.jsonl --start-line 1 --max-rows 500
```

The opt-in public read-only `diverse_languages_qa.yml` workflow can inspect
a **checked-in** candidate JSONL only beneath this extension's `candidates/`
directory with inputs `shard_path`, `start_line`, `max_rows` (1..2000).
It has a 10-minute standard Ubuntu job, read-only permissions, no secrets,
release writes, artifacts, caches, or external downloads. It reports the real
GitHub run ID if triggered; there is **no eligible source or task ID now**.

**Measured state at the reviewed public snapshot (2026-10-13):**
14 IDs; 7 source-cited structural metadata facts; 0 admitted lexical sources,
0 attested production lexemes, 0 reviewed source-language bindings, no
production QA run/checkpoint. Seven identities lack even a reviewed
structural datapoint here. `report()` gives individual readiness and the
unresolved-source status of each language. Tests use synthetic data only;
they do not increase production evidence counts.

## 2026-10-13 row-attestation hardening

The existing Route05 admission and independent language/variety binding gate remain
mandatory. Candidate review additionally accepts optional `source_row_index`
(1-based) and `source_row_sha256` (SHA-256 of the exact raw source JSONL line,
including its line ending). Missing, forged, out-of-range or mismatched row
evidence is blocking, even when a source file has a valid overall hash.
The bound row must exactly match record, language, lemma, meaning, and variety;
this is **not** an authorization to publish the candidate. Source rows and shard
inputs are capped at 40 MiB, resumed line numbers at 1,000,000, and symlink
shard inputs are rejected. Review summaries suppress malformed language IDs.

The read-only QA workflow may also be invoked through a GitHub pull-request
comment with the **exact** body `/diverse-qa` from the repository owner.
On any other comment it skips without executing. Such QA establishes only
engineering test status, never linguistic coverage or redistribution clearance.
