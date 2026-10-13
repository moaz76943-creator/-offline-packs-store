# Independent diverse-language evidence gate

This isolated extension covers 14 registered product identities **separately**:
`sw`, `zu`, `xh`, `rw`, `sn`, `yo`, `ig`, `ha`, `so`, `mg`, `id`, `ms`, `tl`, `am`.
It reads current canonical public `catalog/language_registry.v1.json`, the independent
`content_readiness.v1.json` and `legal/ledger/sources.json` at runtime.
It changes none of those shared contracts and cannot publish content.

**Verified structural evidence:** four individually cited WALS datapoints:
Yoruba (complex tone), Igbo and Hausa (simple tone), Indonesian (the WALS
reduplication category). Author, original reference, publisher, URL, CC BY 4.0
rights and limitations appear in `evidence.json`. These facts do not license
any dictionary, orthographic tone generator, speaker recording or paradigm.
The other ten language profiles contain independent investigation questions,
canonical metadata marked **provisional**, and **zero verified structural facts**.
No unverified feature is promoted to a product capability.

**African language distinctions:** noun classes are explicitly named as a
research area and are never represented as German grammatical gender.
Zulu, Xhosa, Shona, Kinyarwanda and Swahili remain separate identities.
Somali is not substituted by Arabic or Swahili. Malagasy is not replaced
by Indonesian or Malay. Indonesian, Malay and Tagalog have separate questions
for affixation, reduplication and voice/focus; no generalized generator exists.
The canonical registry's dialect relationships are surfaced as relationships,
never as lookup aliases. Tones, marks, prefixes and forms are never invented.

**Source discovery:** review Glottolog 5.3 for language/bibliography identity
and WALS for typological datapoints, then discover grammars, named publishers
and speaker/community participation on a per-language basis. The metadata
sources are *not* preapproved lexeme sources. Check exact license terms,
attribution, permission for redistribution, variants, consent reference and
immutable artifact digest with the existing admission process. Record the
publisher and exact URL; community and consent claims must be independently
proved. Do not download, scrape, or publish from exploratory leads.

**Candidate review (JSONL):** each candidate requires:
`record_id`, `language_id`, `lemma`, `meaning`, `variant`, `source_id`,
`publisher`, `community`, `speaker_consent_ref`, `license`, `rights_url`.
No real speaker identities belong in the file. Consent is represented only by
an externally controlled non-personal reference. Only exact canonical language
IDs are accepted; `fil` must not silently mean `tl`. Source admission needs
one matching rights ledger entry, recorded approval, authorized language,
an immutable on-disk artifact under the approved admission area and matching
SHA-256, plus matching publisher/license/rights URL. No automatic edits.
JSONL is decoded strictly as UTF-8; original text is not rewritten.
Unicode NFC+casefold are used **only** to flag collisions for review.

Run offline from repository root:

```sh
python3 -m unittest discover -s tests/linguistic_extensions/diverse_languages -p 'test_*.py' -v
python3 tools/linguistic_extensions/diverse_languages/audit.py --language yo
python3 tools/linguistic_extensions/diverse_languages/audit.py
python3 tools/linguistic_extensions/diverse_languages/audit.py --input local-candidates.jsonl --start-line 1 --max-rows 500
```

Each bounded invocation reads at most 2,000 candidate lines (default 500),
records a deterministic `next_line` checkpoint, and returns per-language
candidate counts and a line-number-only review queue for mismatched rights,
spelling, sense or provenance. Cross-shard conflicts still need a global
human merge review; shard-level counts **are not** audited production entries.
No text from rejected candidates or speaker/community identifiers appears in
review output. The workflow only runs read-only tests and reports, on PRs or
manual opt-in. No background job is queued while the production rights ledger
is empty. Integrating community contribution intake awaits non-overlapping,
reviewed PRs #88, #93 and #94.

**Current measured state (2026-10-13):** 14 independent profiles; 4 cited
structural datapoints; 0 approved production lexical sources; 0 verified
production lexemes for these profiles; 10 other profiles still require
independent morphological references. The unresolved source list is per-language
`unresolved_source` in the report. These counts do not imply finished
morphology engines or content for any of the fourteen languages.
