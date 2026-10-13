# Curriculum evidence audit — public read-only sidecar v1

Isolated implementation in tools/factory_extensions/curriculum_evidence/, with scoped tests and workflow. It does not edit shared standards, Jules PR #84/#86, the language registry, license ledger, content packs, or app code.

## Contracts and guardrails

- Reads the canonical catalog/language_registry.v1.json (all 100 language identities), standards/proficiency/frameworks.json and tools.proficiency_mapping.engine.ProficiencyCatalog.validate_record.
- Keeps word difficulty, sentence complexity, grammar complexity, script literacy, four separately reported skills, and learner ability separate. Never estimates learner results. Never derives CEFR from frequency rank, JLPT/HSK/TOPIK, orthography or assumed course order.
- An attested level needs the source/version from the canonical proficiency validator, the same content provenance in an explicitly approved Route 05 ledger source, and independent curriculum evidence.
- Reports unknown and unassessed independently of estimated and source_attested. Estimated labels do not count as verified educational content.
- Accepts multiple independently identified curricula per language. Actual prerequisite IDs must resolve, have consistent language/framework/curriculum, and form an acyclic graph. Verified content cannot depend on an unverified predecessor.
- Counts four content kinds (vocabulary, grammar, example, exercise) and optional source-backed topic/situation descriptors and skill-specific material tags. Content tags are NOT measured reading/listening/writing/speaking ability.
- Does not synthesize passing standards, credentials, CEFR equivalence, teaching content or attribution. A TOPIK ID exists in the main language registry but lacks a source-versioned entry in the published proficiency framework standard, so TOPIK level assignments are blocked and the framework gap reported.

## Commands

From the repository root:

    python3 -m unittest discover -s tests/factory_extensions/curriculum_evidence -p 'test_*.py' -v
    python3 -m tools.factory_extensions.curriculum_evidence.audit --output /tmp/curriculum_receipt.json

Once independent licensing and classification review actually approves data:

    python3 -m tools.factory_extensions.curriculum_evidence.audit --input tools/factory_extensions/curriculum_evidence/approved_input.jsonl --output /tmp/curriculum_receipt.json

JSONL is capped at 8 MiB, 10,000 records and 64 KiB per line. Each row supplies record_id, canonical language, kind (vocabulary|grammar|example|exercise), an exact source reference (source_id, dataset_version, artifact_sha256) matching the approved Route 05 ledger, a complete canonical proficiency record, curriculum identity with source_id/source_version/locator, and a list of prerequisite record IDs. Optional taxonomy entries use kind=topic or situation plus value, source_id, source_version, locator, reviewer_id. Optional skill_material entries use skill=reading/listening/writing/speaking and the same per-claim provenance. Full proficiency record schema and human review requirements remain owned by standards/proficiency. The workflow reads only a checked-in approved_input.jsonl if present, and otherwise audits the empty source-backed inventory.

No arbitrary readiness threshold is invented. A separate --criteria JSON object can supply an independently approved ledger source reference, editor reviewer, and minimums for all four content kinds. Meeting those values yields only a NON-ACCREDITED editorial target check, not a qualification or certificate.

## Current evidence gaps — October 13, 2026

- The live legal/ledger/sources.json is empty: zero approved source-backed curriculum classifications are available. No production levels can be called complete.
- The existing standards/proficiency/curricula.json contains five pilot planning tracks with empty inventories, not five completed courses.
- No licensed approved curriculum JSONL or independently sourced editorial sufficiency targets are published in main.
- TOPIK needs its own versioned, publisher-evidenced proficiency framework contract. JLPT's conditional, score-dependent CEFR *reference indication* is handled only in the upstream mapping API. This audit deliberately performs no cross-framework mappings.
- The 100-language audit receipt is structured JSON containing per-language verified/estimated/unassessed counts, per-curriculum and level content counts, independent script/skill/topic/situation coverage, framework gaps, rejected row reasons, input SHA-256 and commit SHA. It is not certification, educational quality accreditation or permission to publish material.
- The 5-minute public read-only Action is defined but hosted success MUST NOT be claimed until GitHub returns a real workflow run/job ID. A commit marked [skip ci] does not prove a hosted test ran. The independent release admission remains a separate gate.

No secrets, network corpus downloads, paid runners, external billing, caching, artifact uploads or release mutations are used.
