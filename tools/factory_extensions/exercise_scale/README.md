# Exercise-scale: evidence-gated multilingual candidate QA

An independent, standard-library-only worker for the 100 registered languages.
No private Flutter, learner state, SRS data, paid services or public publication.

## Canonical integration

Read-only adapters use catalog/language_registry.v1.json, the native Route 05
legal/ledger/sources.json, canonical lexical senses, verified grammar/forms,
directed translation edges, source sentences and proficiency evidence.
GHA-05 make_cloze remains the upstream producer for editor-reviewed spans and
attested forms. Public PR #75 has separate Cloze QA; it is not changed or
copied and is not assumed merged.

The candidate contract requires schema_version 1.0.0 and supports recognition,
recall, multiple_choice, cloze, matching, spelling, verb_conjugation, grammar.
Fields separate language (answer identity), source_language, target_language,
interface_language, script, lexeme_id, sense_id, source_sense_id,
directed_pair_id, grammar_rule_id, proficiency framework/level/evidence ID,
difficulty, features, prompt, correct_answers, ambiguous_answers,
answer_policy, choices, matching_pairs, explanation, cloze_source/span,
optional form_evidence_id, fixture_only, publication_approved, review and
evidence.

Evidence includes independent source_id, publisher, dataset_version, locator,
origin_url, license_id, artifact_sha256, record_sha256, answer_evidence_url.
The source must match the separate approved native rights ledger exactly.
Editorial review needs an approved reviewer decision, reviewer ID/URL,
unambiguity and option review. A directed edge must exactly match source and
target sense/language IDs; inverse and pivot relations are never inferred.
Approved language-specific feature maps permit case, noun classes, agreement,
particles, classifiers and morphology without imposing German universal rules.
Conjugation needs an attested inflected form and feature bundle. Grammar
explanations must match a separately approved rule.

Cloze preserves Unicode source text and validates exact span, answer and
sentence SHA-256. Matching uses independent reviewed edges with no duplicate
answers. Multiple-choice distractors require reviewed non-equivalence; no
randomly generated wrong answers. Trivial/answer-leaking prompts, duplicate
items and repetitive MC answer positions are rejected.

Unicode response grading uses NFC. Optional diacritics only work through
independently approved, explicitly enumerated accepted alternatives. No
universal stripping of Arabic marks, Vietnamese tones or Indic combining
signs. Unattested answers remain UNVERIFIED rather than WRONG.

## Package readiness and trust states

QA receipts are ALWAYS REVIEW_REQUIRED / publication_approved=false. Even
accepted synthetic test fixtures are NOT eligible content. No automatic
promotion occurs. The present Route 05 ledger is empty and the public
catalog readiness states are all unverified: verified educational exercises
are 0 for every registered language, not 100 artificially populated packs.

For future offline Flutter handoff, an external release owner must wrap
independently approved UTF-8 JSONL in a pack manifest with schema_version,
content SHA-256, immutable source snapshot SHA-256, exact script, language
roles, evidence/license and attribution obligations, counts per language,
exercise type and difficulty, and authenticated editorial release receipt.
An importer should reject unsupported contracts and commit packs atomically.
This module is a candidate auditor, NOT the release compiler or pack importer.

Partition replay is bounded at 100000 records and 1 MiB per record, uses
SQLite on temporary disk for uniqueness and emits deterministic checkpoint
and candidate-count reports. Input SHA-256 must match. No snapshots are
downloaded or mutable queues edited. GHA-02 has not admitted exercise jobs,
so no independent run IDs are invented.

## Commands

Run focused synthetic negative tests:
    python3 -m unittest discover -s tests/factory_extensions/exercise_scale -p 'test_*.py' -v

Read-only canonical readiness:
    python3 -m tools.factory_extensions.exercise_scale.engine --repo-root .

Approved immutable shard audit:
    python3 -m tools.factory_extensions.exercise_scale.engine --repo-root . --input /snapshot/partition.jsonl --input-sha256 SHA256 --references /reviewed/references.json --references-sha256 REVIEWED_SHA256 --report /tmp/exercise-report.json

The references file supplies approved senses, pairs, forms, rules, proficiency,
distractors; the CLI always binds canonical languages and source rights from
the repository independently. The scoped Actions workflow runs synthetic
tests and read-only genuine ledger readiness with contents:read only.
