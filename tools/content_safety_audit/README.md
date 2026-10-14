# DEUTSCH-IMPROVE-10 — Independent Content Policy and Privacy QA

**Offline, advisory preflight only.** Not a publisher, source-deletion tool, media-byte classifier, legal authority, or replacement for existing canonical gates. Python standard library only; no API calls, paid services, CI workflow or modifications outside the task's two allowed directories.

## Authority and dependency

- [Content IP policy (Notion)](https://app.notion.com/p/3dd5570dfa81811d9ce7d3250b13e8cc): adopted as a long-term requirement, not proof of completed production implementation.
- [Permission-minimization reference](https://app.notion.com/p/3ef5570dfa818102949cf5644824d8ac): explicit feature owner and demonstrated runtime need required for Android permissions; does not claim the app already has zero permissions.
- [DEUTSCH-IMPROVE-09 PR #192](https://github.com/moaz76943-creator/-offline-packs-store/pull/192): remains Draft. Original source evidence and human rights review are not approved. The authoritative rights gate stays in legal/ledger/admission.py.
- [Private J024 PR #144](https://github.com/moaz76943-creator/deutsch-build/pull/144): read-only reference. Its sample prefix-based authorization is not cryptographic proof; private owner must review. No private code or data is copied into this public task.
- Existing public contribution and release gates retain their authority. The source ledger was empty at task start; neither AI content nor apparently permitted imagery is thereby approved for distribution.

## Policy schema and language coverage

The owner preferences are versioned in policy.json and described in policy.schema.json. Screening uses separate text, image, and audio paths. This version includes only initial lexical hints for ar/de/en/fr/es, **not full 100-language coverage**. Text in other languages receives HUMAN_REVIEW rather than claiming it was screened. Arabic diacritics are preserved. Lexical matches use whole-word boundaries, not substring censorship. A positive explicit prohibited sense gets REJECT for the **candidate**, without touching any original data. Ambiguous words, negations, metaphors, homographs, and underspecified meanings go to HUMAN_REVIEW. Each directed language pair is retained as provided; no reverse-pair inference.

Image tags cannot prove anything about actual pixels or rights. Audio transcripts do not prove waveform contents or rights. As no pixels or waveforms are processed, these media types always require HUMAN_REVIEW unless explicitly high-risk tags cause a candidate REJECT. Human review must independently establish safety and licensing. Even an ALLOW decision means **only no triggers found**, never canonical or publication approval.

## Example input and command

Use synthetic or separately authorized JSONL inputs. Each line describes one independent candidate:

~~~json
{"item_id":"candidate-1","media_type":"text","source_language":"de","target_language":"ar","source_text":"Haus","target_text":"بيت","examples":[{"language":"de","text":"Das Haus ist groß."}]}
~~~

From repository root:

~~~sh
python3 -m unittest discover -s tests/content_safety_audit -p 'test_*.py' -v
python3 -m tools.content_safety_audit.audit --input /path/to/candidates.jsonl > /private/location/content_qa_report.json
~~~

Optional --paths-json reads a JSON array of **public tracked path names only**, detects name patterns suggesting SRS/learner data, and redacts all path names. It does not prove the file contents are free of leaks. Optional --manifest reads an authorized local AndroidManifest.xml snapshot only and flags sensitive permissions for owner review. Neither option modifies files, accesses the private repository or emits underlying data. Without those inputs, privacy and Android assertions must remain UNKNOWN.

Output contains actual ALLOW / HUMAN_REVIEW / REJECT counts, anonymous record indices, reason codes, and an independent rights_status EVIDENCE_REQUIRED. publication_approved is always false. No raw text, asset IDs, paths, credentials, SRS or user values are echoed. Limits: 128 KiB input line, 10,000 records, policy 32 KiB, optional metadata/manifest files 1 MiB. Exit 0 = no candidate flags **not publishable**, exit 1 = review/reject cases, exit 2 = incomplete audit.

## Real evidence, limits and handoff

- Base main: 1f9a4b04be8b757a307f5f7e9d1e851a03174bca.
- Local tests: 28/28 PASS. Test-only CLI example: 4 synthetic records = ALLOW 1, HUMAN_REVIEW 2, REJECT 1; not a production corpus count.
- TEXT_QA: context-aware lexical signals and explicit source/target languages; no claim of semantic AI-classifier coverage for 100 languages.
- IMAGE_QA: metadata/tag screening only; physical pixels **NOT_INSPECTED**; rights always **EVIDENCE_REQUIRED**.
- AUDIO_QA: transcript screening only; waveform **NOT_INSPECTED**; rights always **EVIDENCE_REQUIRED**.
- PRIVACY_QA: protects output from raw learner fields and sensitive public filename patterns, but public file bytes and the private Android manifest were **NOT_VERIFIED**.
- Hosted CI, source legal approval, production QA, media rights/pixel review and private-app security checks: **NOT_RUN / NOT_APPROVED**.

Owner/integration follow-up: reconcile with PR #192 and upstream rights review, use canonical source gates, extend independent sense-aware rules language by language, review uncertain examples without deleting originals, audit actual public tracked bytes in a secured scope, and verify private consumer permission manifest. Draft PR must not merge until dependency, reviewer, and test gates are met. No existing production packs are accepted or published by this task.
