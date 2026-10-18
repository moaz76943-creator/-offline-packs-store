# GHA Factory — Open corpus source admission (2026-10-13)

**STATUS: BLOCKED_SOURCE. Actual accepted production records: 0.** Research is NOT permission to publish, and the inspected Route 05 source registry (`legal/ledger/sources.json` on main at `979d7a332a7d57eed4ab896c6d7bfdbbd4ff377b`) was empty. This work deliberately does **not** edit that file or any existing Jules-owned pipeline, manifest, content pack or workflow.

`reviewed_sources.json` records 12 real upstream candidates with official URLs, publisher, claimed licensing categories and reasons for denial or further review. `source_snapshot_date`, `snapshot_identity`, `artifact_sha256`, `license_evidence_sha256`, and `route05_source_id` are **null until verifiable original bytes and source-specific rights snapshots exist**. The review registry is not a replacement for the Route 05 ledger; no missing data is guessed. A SHA-256 of this review JSON is not a substitute for the original artifact and license-notice hashes.

## Independent rights conclusions

- Wiktionary/Kaikki: Wiktionary text is under CC BY-SA and GFDL. Wiktextract's **MIT code license** must not be applied to extracted content. Consider excerpt/quotation and human-audio rights separately; pin exact Wiktionary dump and Kaikki extraction revision. Publisher notices: https://en.wiktionary.org/wiki/Wiktionary:Copyrights and https://kaikki.org/dictionary/rawdata.html.
- UniMorph: the *individual* `deu`, `ara`, `eng`, `spa`, `fra` dataset repositories report **CC BY-SA 3.0**. Route 05 schema currently does not list this license ID. Owner must decide support, compliance and version compatibility; never silently treat 3.0 as 4.0. Dataset directories are not interchangeable with software licenses.
- PanLex: official website says its snapshots are **CC0** and may be used commercially (https://panlex.org/license). But original sources carry individually registered claims; upstream literature explicitly warns those rights could constrain reuse. Review the exact snapshot and underlying source provenance before an approved record is created (https://dev.panlex.org/source-registration/).
- Tatoeba: bulk sentence text defaults to **CC BY 2.0 FR** with an explicit **CC0 subset**; licensing and attribution are per sentence and author. Human audio is **separate per recording and speaker**; no license / noncommercial license => no commercial import. https://tatoeba.org/eng/downloads and https://en.wiki.tatoeba.org/articles/show/faq. Route 05 cannot currently encode CC BY 2.0 FR.
- CEFRLex: the FLELex, EFLLex and ELELex download pages identify **CC BY-NC-SA 4.0**. Commercial product imports are rejected. CEFR frequency distributions are not certified CEFR levels for every word. https://cental.uclouvain.be/cefrlex/.

CC BY, CC BY-SA, CC0 and GFDL have different obligations. License coexistence, separate content classes, derivative works, per-speaker permissions, and media/music copyrights require independent checks. No blanket `PUBLIC_DOMAIN_ZERO_COPYRIGHT` statements are accepted.

## Route 05 ownership and successful admission procedure

1. Have the **Route 05 owner**, not this pipeline, obtain immutable original bytes, source-specific rights evidence, publisher details, snapshots/versions and public human review decision. Both source and license evidence must be captured as actual public files, with separately verified SHA-256 hashes. Introduce unsupported license-family support only through Route 05 owner-reviewed changes.
2. The Route 05 owner adds an independently reviewed entry with `APPROVED_FOR_REDISTRIBUTION` to `legal/ledger/sources.json` using its existing schema and validator. The gate **reads the ledger** and independently checks its paths, statuses, versions and hashes; it cannot set the status itself.
3. For a specifically approved Wiktextract **dictionary** JSONL file from that exact entry (no auto-download), run:

   `python3 tools/gha_factory/admission/pipeline.py --repo-root . --ledger-source-id EXACT_ID --input PATH_IN_ROUTE05_LEDGER --language de --dataset-version EXACT_VERSION --out tools/gha_factory/admission/accepted/BATCH_ID --part-size 1000`

   `ar`, `en`, `es` and `fr` are equally eligible **only when their source versions are separately approved**. Other identities must already exist in `catalog/language_registry.v1.json` (100 registered). Metadata registration is not content availability.
4. The tool validates strict UTF-8, newline-terminated JSONL, bounded line lengths, language match, vocabulary fields, source hashes and record license conflicts. It writes exact source-line hashes, immutable deterministic partition names, SHA-256 and resume IDs, and `queue.json` into a new output directory using staging and rename. Sentences, recordings, fabricated translations and computed CEFR are **excluded**, not silently licensed. Errors leave no output.
5. A future GitHub Actions queue may discover `queue.json` only from successful, reviewed admissions. `ACCEPTED_FOR_QUEUE` is **not** a release decision: the Route 05 owner must still record release candidates, verify notices/copy-left compliance and run its publication gate. `publication_approved=false` is deliberate. No workflow is enabled or CI minutes consumed by this PR.

## Commands

`python3 -m unittest discover -s tests/gha_factory/admission -p 'test_*.py' -v`

`python3 tools/gha_factory/admission/pipeline.py --help`

Standard library only; no remote API, no credentials, no private inputs. Fixture tests use artificial local data and are never production corpus records.
