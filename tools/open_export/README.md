# Community corpus integration — fail-closed contract

This branch reconciles Jules PRs #88, #94, #100, and #101 without merging,
closing, or publishing anything. It is isolated from the private Flutter app
and does not modify production corpora, shared standards, or CI.

## Trust boundaries

* Intake treats bundles as untrusted. Its bounded, schema-validated output
  is STAGED_REVIEW_REQUIRED, never publication permission.
* An authorized validation service and a human reviewer must independently
  sign exact submission, revision, SHA-256, metadata, actor, and action.
  HMAC keys must be provisioned outside contributor directories, review
  storage, and the repository. Caller-provided booleans or rights assertions
  do not authorize publication.
* The export step independently checks the repository rights ledger using
  legal.ledger.admission.evaluate and verifies signed review handoffs and
  actual bytes. Synthetic fixtures cannot constitute production rights proof.
* Export is deliberately limited to evidence-supported CC0-1.0 and PUBLIC-DOMAIN.
  It blocks CC-BY-SA/GFDL until obligation handling is separately reviewed.
  An automated gate never constitutes a legal opinion.
* The live legal/ledger/sources.json currently has no approved sources:
  real export must fail closed until authoritative evidence is added.

## Run locally

The implementation is importable and executable from the repository root.
It uses standard Python plus the repository's existing lexical JSON schema
validation dependency.

1. Intake: python -m community.contributions.ingest INPUT.json --staging-root STAGING
2. Review operator CLI: python -m community.review.cli --storage REVIEW --artifacts STAGING/staged --operator-keys /protected/keys.json submit --id ID --sha256 SHA --artifact STAGING/staged/SHA.bin --metadata /operator/review.json
3. Start review validation with action start. For validate, approve and reject
   supply actor and token from the separate authorized signing authority.
   Then use action eligible to produce a verified handoff, not publication.
4. Place an operator-curated export manifest.json in STAGING/staged with items:
   id, type, filename, sha256, submission_id, source_id, source_version,
   license. These must match verified review and legal records exactly.
5. Export: python -m tools.open_export.exporter --source STAGING/staged --output OUTPUT --review-root REVIEW --operator-keys /protected/keys.json

Keys JSON: validators and reviewers maps, each actor name mapped to a base64
encoded random secret at least 32 bytes. File mode must be 0600.
Actual enrollment, custody, separate human review, revocation, and signing
service remain duties of the coordinator and legal/provenance authorities.

## Boundedness, atomicity and tests

* Intake: packed <= 8 MiB; expanded <= 16 MiB; <= 128 archive members;
  plain JSON, JSON.gz, flat ZIP and flat tar.gz only; no symlinks/traversal.
* Export: <= 128 files; each <= 8 MiB; aggregate <= 16 MiB;
  deterministic content-addressed ZIP with source/attribution records.
* A failed export keeps the prior known-good local CURRENT.json pointer.
  No network calls, publication, or corpus promotion occur.
* Test: python -m unittest discover -s tools/open_export -p test_lifecycle.py -v
* Tests use simulated rights/reviewer evidence. Their success does not prove
  actual source licenses, human authorization, or legal suitability.

## Remaining integration blockers

- Coordinator code review, real repository-runtime verification and merge.
- Populate the authoritative rights ledger with real inspected sources and
  exact version/artifact/rights evidence; all publication remains blocked now.
- Establish reviewer/validator identity enrollment, secure independent key
  management, signature issuance, revocation, audit retention.
- Build an operator-controlled adapter from intake receipt to export manifest,
  without automatically promoting staged or unverified content.
- Review non-CC0 copyright/license obligations and any later publishing flow.

## Original PR mapping

- #88: retains lexical validation and staging approach, supersedes unsafe
  archive extraction and its brittle patch_ingest.py script.
- #94: retains review states and atomic handoff intent, replaces unchecked
  submission paths and self-declared reviewer approval.
- #100: superseded exporter alternative; forbidden UNVERIFIED_RIGHTS
  admission and unbounded decompression are not carried over.
- #101: preferred architectural foundation for deterministic incremental
  output, rewritten with rights-verified handoffs, bounds and cache checking.

Keep original Jules PRs open until disposition is confirmed by the coordinator.
