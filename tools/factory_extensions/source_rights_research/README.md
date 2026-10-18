# Source rights research — evidence collection, NOT admission

This isolated extension never writes to Route05 legal/ledger or the production manifest and cannot set APPROVED_FOR_REDISTRIBUTION. Nine candidates are in candidates.json, none admitted or downloaded.

## Live source review (13 October 2026)
- Canonical catalog/language_registry.v1.json contains 100 language IDs.
- The Route05 source ledger has zero admitted source records.
- PR #78 proposes compatibility checks only; this does not determine original record rights.
- PR #83 proposes an attribution generator operating on approved ledger entries.
- PR #93 proposes a contributor gate; contributor declarations do not prove original publisher authorization.
- None of these owned PR paths have been changed by this extension.

## Research rights matrix (official project statements; not approvals)

| Source | Kind | Advertised rights | Blocking legal questions |
|---|---|---|---|
| Wiktionary via Kaikki | dictionary | CC BY-SA/GFDL source; MIT Wiktextract tool | Exact revision, author notices, GFDL choice, quotes and Commons audio |
| Wikidata Lexemes | dictionary | CC0 structured Lexeme namespace | External sourced records, off-namespace text/media rights |
| UniMorph German | morphology | CC BY-SA 3.0 (README), Wiktionary-derived | License compatibility, exact repo SHA, upstream authors |
| UniMorph Schema | grammar | NOT VERIFIED for this use | Grammar metadata does not license copied teaching prose |
| Tatoeba sentences | sentences | CC BY 2.0 FR; CC0 subset | Each record, attribution, Tanaka-origin work |
| Tatoeba audio | pronunciation | Per contributor | Recording and underlying text separate |
| PanLex | dictionary | PanLex CC0 database snapshots | Original source copyrights, PanLex-only permissions, database scope |
| Common Voice | pronunciation | Dataset CC0 generally; code MPL 2.0 | Non-mirroring request, per-release scope, voice privacy |
| Unicode CLDR | metadata | Unicode License v3 data files generally | Exceptions, exact release, required notices |

PanLex conflicting claims: https://panlex.org/license offers snapshot data under CC0; https://dev.panlex.org/source-registration/ documents copyright-only, no license and permission granted to PanLex, while https://dev.panlex.org/acquisition-principle/ acknowledges legal controversy. This source stays blocked for human legal analysis of underlying source rights and extraction, not automatically approved because of the top-level CC0 statement.

Mozilla Common Voice: https://commonvoice.mozilla.org/dav/terms describes public CC0 dataset distribution but requests no mirroring outside Mozilla Data Collective. Until commercial distribution terms, applicable release-level exceptions and speaker rights are reviewed, it stays blocked.

## Research queue and 100-language coverage

From repo root:
    python3 tools/factory_extensions/source_rights_research/audit.py --out /tmp/rights-research

The rights_audit.json report contains human_approval_queue for every candidate and a language_coverage entry for each of the 100 canonical IDs. Only de is explicitly mapped here to a UniMorph German research candidate; 99 lack individually verified per-language candidate mappings. THIS DOES NOT MEAN those 99 languages are objectively under-resourced; actual per-language corpus sizes and legal-rights coverage have not been measured. All language entries report zero source bytes verified and zero redistribution approvals.

Optional bounded public license evidence capture:
    python3 tools/factory_extensions/source_rights_research/audit.py --out /tmp/rights-research --capture-public-evidence

It fetches only checked-in allowlisted official HTTPS license-page URLs, forbids redirects, restricts pages to 256 KiB each / 1 MiB total and 8-second timeout, and does not download corpora. Page hashes and snapshots are human-review artifacts only, never source-admission evidence without further validation and authenticated signoff.

## Human-only handoff checklist
1. Identify exact publisher, dataset version, date of acquisition, immutable source artifact and SHA-256.
2. Collect source-specific official license text/snapshot SHA-256, full original authorship, notices, modification history and source-specific URLs.
3. Resolve contributor, record, translation, audio, ShareAlike, noncommercial, dual-license, database and commercial redistribution constraints.
4. Record file-level and per-record licenses and separate extraction-tool rights; establish a legally compatible output.
5. Obtain an authorized human decision linked to pinned dataset and evidence; then independently pass the existing Route05 ledger validator. A green research QA can NEVER mark APPROVED_FOR_REDISTRIBUTION.

Adversarial test command:
    python3 -m unittest discover -s tests/factory_extensions/source_rights_research -p 'test_*.py' -v

Run existing Route05 regression separately. The workflow is read-only, standard Ubuntu, no paid services, no secrets, no publishing. [skip ci] commits require explicit exact-commit hosted testing; an automatically skipped run is not proof.
