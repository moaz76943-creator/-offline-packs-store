# Indic and Southeast Asian orthography extension

## Scope and truth

This module is scoped to 18 separate public product language IDs:
hi, mr, ne, bn, as, pa, gu, or, ta, te, kn, ml, si, ur, th, lo, km, my.

Each language and script must match the actual public registry at
catalog/language_registry.v1.json. Bengali and Assamese, Hindi/Marathi/Nepali,
and other related languages are NOT lexical aliases. The Urdu identity is
Indo-Aryan written in an Arabic-derived script; Arabic root/pattern grammar
must not be imported as a default. Punjabi can have Gurmukhi and Shahmukhi
representations, but automatic equivalence across them is not asserted.

The published registry morphology features are provisional metadata, NOT
independently verified form inventories. All language-specific candidate
morphological fields remain evidence-required.

## Interfaces

- profile(code, registry): cross-check the separate scripts/identities against
  canonical public metadata; report evidence-required candidate capabilities.
- validate_text(code, text): return the exact original Unicode sequence,
  original UTF-8 digest, and a separate NFC-only search key. No NFKC,
  transliteration, spelling substitution or unsupported lexical equivalence.
- orthographic_units(code, text): preserve common conjunct and vowel-sign
  display sequences. This is deliberately not claimed to implement the entire
  Unicode UAX #29 grapheme-boundary specification.
- words(code, text): Indic whitespace produces only orthographic hints, not
  recognized lexical tokens. Thai/Lao/Khmer/Myanmar require explicit approved
  source-backed segmentation; no whitespace-based guesses.
- search_relation(code, a, b): report Unicode canonical equivalence only;
  everything else remains undetermined until separately evidenced.
- validate_attestation(record, code, registry, ledger): strict per-language,
  per-script, evidence-approved exact morphology records only. No generated
  inflection, noun class, agreement, postposition, tone or honorific assertion.
- audit_jsonl(path, code, registry, ledger): bounded read-only language-specific
  evidence worker (4 MB input, 2,000 records, 64 KiB per line) with actual
  unique lexeme/form counts and input SHA-256.

## Independent admission hash contract

The release-approval ledger input must itself come from an authenticated,
independent review process; accepting a caller-provided dictionary is not
cryptographic proof of legal rights or independent linguistic review.

An eligible source record must contain its unique `id`, `languages`,
`sha256`, `release_approved: true`, `rights_status: APPROVED`,
non-empty `reviewed_by`, `rights_evidence_sha256`, and a
`reviewed_records` map with exactly `morphology`, `segmentation`,
and `orthographic_relation` lists of lower-case SHA-256 digests.
Each digest is calculated from the **complete reviewed JSON record** via
canonical JSON with UTF-8, sorted keys, no ASCII escaping, and compact
separators. A record not explicitly present in its source's exact reviewed
digest set is rejected, even when the language, source ID, and source snapshot
hash look plausible. Release rights, reviewer identity and independently
approved source bytes still require upstream verification.

Synthetic unit tests make their own mock in-memory ledger, deliberately
not written to `legal/ledger/sources.json` and never used in a release.
Digest lists and worker input sizes are capped to preserve bounded RAM.
A zero-row JSONL audit must not report `PASS_EVIDENCE_QA`.

Segmentation evidence requires exact reconstructable tokens, language,
source ID, a matching source-ledger SHA-256 and an input-text digest.
Morphology evidence uses exact, language-scoped lemma and sense IDs. The
extension never uploads, downloads, commits, or publishes any lexemes.

## Production coverage and unresolved issues

The public legal source ledger is currently empty. Thus the real admissible
lexeme/form coverage is 0 verified records per language. Unit tests use
synthetic Unicode samples and a synthetic IN-MEMORY approved source for the
fail-closed acceptance contract. These are not licensed production content.

Unresolved for a full certification: Unicode UAX #29 grapheme boundary
conformance, Myanmar stacked/medial clusters, Khmer coeng and preposed
vowels, Malayalam chillu and Indic virama exceptions, Thai/Lao dictionary
segmentation, Punjabi cross-script and Urdu spelling/Arabic joiner variants.
Related forms and transliterations require reviewed source evidence and
explicit relation classes; NFC alone is not proof of lexical identity.

## Local read-only verification

    python3 -m unittest discover -s tests/linguistic_extensions/indic_seasian -p 'test_*.py' -v
    python3 -m tools.linguistic_extensions.indic_seasian.processor --language ur
    python3 -m tools.linguistic_extensions.indic_seasian.processor --language th

Public GitHub Actions: .github/workflows/indic_seasian_qa.yml. It uses a
standard Ubuntu runner, read-only contents, no dependency installation,
no private code and a 12-minute maximum duration. It checks every canonical
language identity, plus 18-language positive/negative Unicode test coverage.
No corpus processing is dispatched when the approved-source ledger is empty.
