# Language production status

Scheduled production is language-generic. Each run takes one bounded slice of the
Wikidata lexeme dump and writes per-language overlays that share concept ids.
Directed translation pairs are not stored. Sentences stay empty until the owner
approves a compatible sentence source.

Dump date: none yet
Batch slot: n/a
Slice bytes: n/a
Checksum verified: false
Quarantined records: 0
Excluded by content policy: 0

| Language | Lexemes | Sections | Estimated levels | Quarantined |
| --- | ---: | --- | --- | ---: |
| — | 0 | — | — | 0 |

Level labels are `estimated:heuristic-v1`, not corpus bands.
Kill switch: set repository variable `LANGUAGE_PRODUCTION_HALT` to `true` to stop scheduled runs.
Sentence source: issue titled `Source decision: Tatoeba`. Only `moaz76943-creator` can approve it with a line `decision: approve`.

## Organization coverage

Language profiles: 100 registry languages. Concept graph: 5,182 Wikidata-anchored concepts across 20 sections. Redistributable concept fill: 0. Open concept gaps: 5,182 per language, 518,200 across the registry. No word is invented to close a gap. Shopping has 15 concepts because that is the Wikidata instance/subclass count for its class, not a padded list.

| Source | Stated license | Ledger-compatible | Candidate rows |
| --- | --- | --- | --- |
| Kaikki/Wiktextract | CC-BY-SA-4.0 and GFDL | yes, unpublished | only records with a Wikidata anchor |
| Tatoeba | CC-BY-2.0-FR | no | attributed sentences only, author required |
| Universal Dependencies | per treebank | only when that treebank notice matches CC-BY-SA-4.0, GFDL, or CC0 | morphology from an accepted treebank |
| UniMorph | CC-BY-SA-3.0 | no | none |
| Apertium English | GPL-3.0-only | no | none |
| OmegaWiki | unverified | no | none |

Redistributable concept fill: 0. Candidate sentence fill: 0. `publication_approved` stays false.
