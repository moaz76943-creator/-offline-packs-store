# Curriculum evidence audit — public read-only sidecar v1

Isolated implementation in tools/factory_extensions/curriculum_evidence/, with scoped tests and workflow. It does not edit shared standards, Jules PR #84/#86, the language registry, license ledger, content packs, or app code.

## Contracts and guardrails

- Reads the canonical catalog/language_registry.v1.json (all 100 language identities), standards/proficiency/frameworks.json and tools.proficiency_mapping.engine.ProficiencyCatalog.validate_record.
- Keeps word difficulty, sentence complexity, grammar complexity, script literacy, four separately reported skills, and learner ability separate. Never estimates learner results. Never derives CEFR from frequency rank, JLPT/HSK/TOPIK, orthography or assumed course order.
- An attested level needs the source/version from the canonical proficiency validator, the same content provenance in an explicitly approved Route 05 ledger source, and independent curriculum evidence.
- Classification source approval additionally requires checked-in original snapshot bytes matching recorded SHA-256 and separately checked-in source-specific license evidence bytes matching recorded SHA-256; repository path escapes and symlink escapes are blocked. Bounded reads: 256 MiB source, 2 MiB license evidence per distinct source identity. The proof decision URL and reviewer metadata are checked structurally, not cryptographically certified. Never treat this validator as a legal opinion.
- Reports unknown and unassessed independently of estimated and source_attested. Estimated labels do not count as verified educational content.
- Accepts multiple independently identified curricula per language. Actual prerequisite IDs must resolve, have consistent language/framework/curriculum, and form an acyclic graph. Verified content cannot depend on an unverified predecessor.
- Every prerequisite relation additionally needs its own reviewed source/version, exact predecessor record ID, locator and reviewer ID in `prerequisite_evidence`. A curriculum ID cannot silently span incompatible proficiency frameworks. Rejecting unsafe relations invalidates dependent coverage; no unproven progression is published.
- Counts four content kinds (vocabulary, grammar, example, exercise) and optional source-backed topic/situation descriptors and skill-specific material tags. Content tags are NOT measured reading/listening/writing/speaking ability.
- Does not synthesize passing standards, credentials, CEFR equivalence, teaching content or attribution. TOPIK is declared in the main registry without a versioned proficiency-standard entry. Chinese is registered there as HSK, whereas the published proficiency standard identifies HSK_3_0: both unresolved identity/version mismatches are reported as gaps, never silently equated or used to assign levels.

## Commands

From the repository root:

    python3 -m unittest discover -s tests/factory_extensions/curriculum_evidence -p 'test_*.py' -v
    python3 -m tools.factory_extensions.curriculum_evidence.audit --output /tmp/curriculum_receipt.json

Once independent licensing and classification review actually approves data:

    python3 -m tools.factory_extensions.curriculum_evidence.audit --input tools/factory_extensions/curriculum_evidence/approved_input.jsonl --output /tmp/curriculum_receipt.json

JSONL is capped at 8 MiB, 10,000 records and 64 KiB per line. Each row supplies record_id, canonical language, kind (vocabulary|grammar|example|exercise), an exact source reference (source_id, dataset_version, artifact_sha256) matching the approved Route 05 ledger, a complete canonical proficiency record, curriculum identity with source_id/source_version/locator, and a list of prerequisite record IDs. Optional taxonomy entries use kind=topic or situation plus value, source_id, source_version, locator, reviewer_id. Optional skill_material entries use skill=reading/listening/writing/speaking and the same per-claim provenance. `prerequisite_evidence` is a list matching every `prerequisites` ID one-to-one, with `{record_id,source_id,source_version,locator,reviewer_id}`; empty prerequisites require an empty or omitted evidence list. Full proficiency record schema and human review requirements remain owned by standards/proficiency. The workflow reads only a checked-in approved_input.jsonl if present, and otherwise audits the empty source-backed inventory.

No arbitrary readiness threshold is invented. A separate --criteria JSON object can supply an independently approved ledger source reference, editor reviewer, and minimums for all four content kinds. Meeting those values yields only a NON-ACCREDITED editorial target check, not a qualification or certificate.

## Current evidence gaps — October 13, 2026

- The live legal/ledger/sources.json is empty: zero approved source-backed curriculum classifications are available. No production levels can be called complete.
- The existing standards/proficiency/curricula.json contains five pilot planning tracks with empty inventories, not five completed courses.
- No licensed approved curriculum JSONL or independently sourced editorial sufficiency targets are published in main.
- TOPIK needs its own versioned, publisher-evidenced proficiency framework contract; the HSK versus HSK_3_0 identity/version discrepancy needs an upstream contract decision. JLPT's conditional, score-dependent CEFR *reference indication* is handled only in the upstream mapping API. This audit deliberately performs no cross-framework mappings.
- The 100-language audit receipt is structured JSON containing per-language verified/estimated/unknown/unassessed counts, per-curriculum and level content counts, independent script/skill/topic/situation coverage, framework gaps, rejected row reasons, input SHA-256 and commit SHA. It is not certification, educational quality accreditation or permission to publish material.
- The 5-minute public read-only Action is defined but hosted success MUST NOT be claimed until GitHub returns a real workflow run/job ID. A commit marked [skip ci] does not prove a hosted test ran. The independent release admission remains a separate gate.

No secrets, network corpus downloads, paid runners, external billing, caching, artifact uploads or release mutations are used.

A source-derived baseline receipt, baseline_main_254e8edd.json, records the full 100-language catalog and exact upstream blob SHAs, with zero admitted classifications and HSK/TOPIK gaps. This snapshot was computed from live canonical input metadata, not from an Actions run or a production corpus audit.

## Hardening validation

- Run `python3 -m unittest discover -s tests/factory_extensions/curriculum_evidence -p 'test_*.py' -v` (25 scoped tests: local fixture-only, RED→GREEN proof, no real approvals).
- Verify exact merged Git blobs and run the public bounded workflow on the merged commit; until a hosted job ID exists, status remains **NOT_RUN**.
- This hardening is sidecar-only; it does **not** repair the underlying missing source approvals, HSK versus HSK_3_0 identity or unregistered TOPIK standard. Those must be independently resolved by their owners.
