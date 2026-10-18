# CJK lexical intelligence (isolated public contract)

This module contains **no production lexical records**. The tests use synthetic
fixtures to exercise matching rules; they are **not licensed corpus evidence**.

## Accepted input contract

Each unit contains language (`zh`, `ja` or `ko`), source-bound lexical ID,
surface, POS, script, stable sense ID, source ID, source revision, and
`approved: true`. This flag is a *caller assertion*, **not** independent
verification of upstream source licensing. The upstream source-admission gate
must verify license, immutable dataset identity, attribution and manifest hash
before passing records here. This module never downloads corpora or models.

Each attested reading has its own ID, source ID, sense ID, language, text and
transcription system. Cross-language transfer is forbidden. Framework levels
require explicit HSK/JLPT/TOPIK evidence IDs; there is no auto-assignment.

Attested simplified/traditional forms, Japanese inflected words and readings,
Korean forms and speech levels, Chinese classifiers or tone variants are
represented as **separate admitted lexical surfaces or evidence-tagged
features**. A bare character or suffix does not become a translation simply
because a tokenizer saw it.

## Bounded dictionary segmentation

`Segmenter(language, units).segment(text)` uses Unicode NFC lookup, maximal
attested surface matching, 32-codepoint maximum dictionary keys, a hard 100k
record cap, and 200k-codepoint input cap. Matching retains separate homograph
sense records. Unmatched text is explicitly marked as such. This is a bounded
dictionary matcher, **not** a trained Chinese/Japanese/Korean morphological
analyzer; it does not infer syntactic boundaries, particles, new conjugations,
reading probabilities or contextual word senses.

Input raw orthography is kept in source units. Offsets in segmented output
refer to NFC text; callers needing original decomposed offsets must maintain
their own normalization offset map.

## Current QA and production limitations

Run `python3 -m unittest discover -s tests/linguistic_extensions/cjk -p 'test_*.py' -v`.
The GitHub workflow only tests synthetic cases; it never publishes output packs.
`evaluate_partition` reports actual accepted distinct unit counts, accepted
and unmatched segments, CPU seconds, and a SHA-256 digest for supplied texts.
This cannot certify dataset provenance or end-user linguistic coverage.

Real 100-language-scale corpus jobs require **independently approved immutable
partitions**, their verified SHA-256 manifests, and the existing public queue
contract. No external segmentation models, source datasets, background jobs,
GitHub Action dispatches or production packs are included in this isolated PR.
