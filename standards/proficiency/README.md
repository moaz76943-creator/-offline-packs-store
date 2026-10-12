# Proficiency contracts — v1.0.0

This public, **offline-only** package provides **data labels**, not tests, learner
scores, accreditation, approved certificates, or actual lessons. It publishes no
learner data. It uses only Python's standard library.

## Stable identities and boundaries

- `proficiency_framework_id` and `proficiency_level_id` are separate. A level
  has meaning only within an identified, versioned framework.
- CEFR A1–C2 is a descriptive framework. The three generic pedagogical bands
  are **independent**, uncertified labels, with **no automatic conversion**.
- JLPT N5–N1 emphasizes **receptive** Japanese (reading/listening), not spoken
  or written production. Its official **reference indication** of CEFR depends
  on passing the test and the total score; it **does not certify all CEFR skills**.
- HSK 3.0 and China's GF0025-2021 nine-level standard are separate versioned
  identities. HSK 7–9 have a combined advanced assessment arrangement; those
  identities do **not** imply separate valid examination scores for each band.
  HSK, JLPT, generic bands and CEFR are never presumed equivalent.
- Extra national / institutional systems may be registered with distinct IDs,
  versions, verified publisher sources and their own level sets. A new registry
  entry is **not** an assertion of equivalence or certification.
- `unknown` and `unassessed` are explicit; both prevent an assigned level.
  Distinct word, sentence, grammar and reading attributes prevent frequency
  rank or word difficulty from silently inflating a learner's CEFR ability.
- Four separately modeled skills indicate receptive vs productive direction.
  Unicode script literacy, topic domains and bounded prerequisite identifiers
  are separately stored. Neither a script nor a language family determines a
  global difficulty curve.
- An `estimated` record needs descriptor-guided **human** review with an
  identifiable reviewer and exact registered framework source version/URL;
  it is never an official CEFR qualification. `source_attested` requires a
  separately curated content-assignment source and verified SHA-256 provenance.
  Editing the source registry does **not** verify a publisher or its claims.
- Corpus frequency evidence, when provided, is **auxiliary only**. No frequency
  threshold is used to assign proficiency.

## Files

- `frameworks.json`: source-backed framework IDs, source identities and versions.
- `record.schema.json`: strict JSON Schema 2020-12 for individual records.
- `mappings.json`: only published JLPT score-conditioned *reference indications*;
  estimated mappings have their own separate list and must be explicitly enabled.
- `pilot_fixtures.json`: de/ar/en/es/fr unassessed examples (no fake labels).
- `curricula.json`: six CEFR **planning stages** for each pilot language; empty
  content inventories prove that course assets have **not** been manufactured.
- `tools/proficiency_mapping/engine.py`: executable validator and mapping API.

## Offline commands (repository root)

```sh
python3 -m tools.proficiency_mapping validate
python3 -m tools.proficiency_mapping map JLPT N3 CEFR --passed --score 104 --skill reading
python3 -m unittest discover -s tools/proficiency_mapping -p 'test_*.py' -v
python3 -m compileall -q tools/proficiency_mapping
python3 -m unittest discover -s standards/proficiency -p 'test_*.py' -v
git diff --check
```

Mapping API results explicitly distinguish `published_reference`,
`estimated_not_official` and `unknown`. Comparison is **direct only**—no
transitive chaining, extrapolation or automatic progression.

## Source identity and validity

Council of Europe (2020 Companion volume):
https://www.coe.int/en/web/common-european-framework-reference-languages/introduction-and-context

JLPT level definitions: https://www.jlpt.jp/e/about/levelsummary.html

JLPT score-conditioned CEFR reference indication:
https://www.jlpt.jp/e/about/cefr_reference.html

Chinese Testing International, New HSK: https://www.chinesetest.cn/HSK

PRC Ministry of Education, GF0025-2021:
https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/202103/t20210329_523304.html

An offline schema validator checks formats, identity, source consistency,
conflicting ranges, cross-record cycles, and classification evidence gates.
It **cannot verify** live publisher content, source licensing, actual exam
results, a reviewer's real identity, or genuine source publication. Qualified
curation and source retrieval verification remain separate preconditions to
publishing any new certified-looking claims.
