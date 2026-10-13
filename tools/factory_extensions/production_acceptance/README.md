# Production acceptance: read-only, fail-closed contract

Authority: `manifest.json`, `version.json`, `catalog/language_registry.v1.json`, `catalog/content_readiness.v1.json` and `legal/ledger/**`. This adapter **never** edits those sources, invents a parallel manifest, signs a pack, publishes, or imports the private Flutter app.

## Verification chain

1. Source: exact `source_id`, immutable `dataset_version` and retrieval SHA-256 in Route 05 ledger; Route 05 admission must independently clear artifact, license, attribution, derivative and manual-review rules.
2. Candidate: registered `language`, monotonic semantic `version`, exact non-fixture archive SHA-256, non-symlink repository-local bytes. Fail on path escape and oversize.
3. Integrity: invoke existing strict `tools.gha_factory.pack_conformance.check.inspect` for canonical SQLite v2, FK, full FTS5, Unicode and bounded gzip/envelope checks (which itself reuses GHA-06). Do not replace or weaken that validator.
4. Educational provenance: eight **separately signed** category receipts: `lexical`, `morphology`, `sentences`, `translations`, `grammar`, `license`, `attribution`, `candidate_qa`. Each must include `kind`, `result: PASS`, actual positive `run_id`, and identical `language`, `version`, `pack_sha256`, `source_id`, `dataset_version`, `source_sha256`. Source/license eligibility remains independently verified by Route 05. Claims in a JSON file alone do not pass.
5. Authenticity: receipts use Ed25519 detached signatures of `b'DEUTSCH-PUBLIC-ACCEPTANCE-v1\\x00' + canonical_json(payload)`. Public-key SHA-256 pins must be supplied from trusted policy **outside the candidate data**; private keys never enter PUBLIC. A SHA-256 checksum or a public-secret HMAC cannot authenticate publishers.
6. Rollback: publisher-signed `release_state` with `kind: release_state`, exact language, and `mode: GENESIS` (only when no published canonical entry) or `mode: LAST_KNOWN_GOOD` (with version and sha256 exactly matching a canonical published pack and surviving `packs/<language>-<version>.pack.gz` bytes). The new version must exceed that signed version. Optional `--previous-version` is an additional lower bound; it is **not** an authoritative replacement.
7. Handoff: publisher-signed `authorization` payload must have `kind: publication_authorization`, `decision: APPROVE`, positive real `run_id`, and matching language/version/pack/source hashes. Successful evaluation is **VERIFIED_FOR_AUTHORIZED_HANDOFF**, never PUBLISHED and never an app-installation certification. Only GHA-06/Route 13 publication owners may update the canonical manifest.

The adapter is deliberately stricter than a general source inventory. An independent receipt from a process that did not actually inspect the content is invalid operational evidence even when the JSON signature is well-formed. The receiving release owner must verify the claimed workflow run and trusted key provenance before taking any publication action.

## Input envelope

A candidate bundle is a JSON object with:
- `candidate`: `{language,version,sha256,fixture_only:false,source:{source_id,dataset_version,sha256}}`
- `proofs`: exact keys listed above; every value `{payload,signature}`.
- `release_state`: `{payload,signature}`; signed publisher key, canonical version floor.
- `authorization`: `{payload,signature}`; independent publisher approval.

Both signatures are base64-encoded 64-byte Ed25519 signatures. Key paths and pinned key digests are CLI arguments from an external trust configuration. No key, unsigned proof, replay, same-version release, substituted language, mismatched byte hash, source drift or absent QA receipt is accepted.

```bash
python3 -m unittest discover -s tests/factory_extensions/production_acceptance -v
python3 -m tools.factory_extensions.production_acceptance.audit --root . --output /tmp/coverage.json
# Only for an *actual* admissible candidate and independently trusted keys:
python3 -m tools.factory_extensions.production_acceptance.audit --root . \
  --bundle /secure/candidate.json --archive packs/de-1.0.0.pack.gz \
  --qa-public-key /trusted/qa.pub.pem --qa-key-sha256 SHA256_FROM_TRUST_POLICY \
  --publisher-public-key /trusted/publisher.pub.pem \
  --publisher-key-sha256 SHA256_FROM_TRUST_POLICY
```

## Language dashboard and truth states

The emitted JSON provides all 100 stable language IDs, seven ordered readiness stages and nine requested counts. Unknown metrics are `null`, **not zero**. Stages are `PASS`, `FAIL`, `NOT_EVIDENCED`, or `NOT_APPLICABLE` in the acceptance vocabulary; this initial read-only snapshot asserts only the registered identity, and reports every remaining stage as `NOT_EVIDENCED` until signed domain-specific evidence and a real integration exist. A signed `NOT_APPLICABLE` requires a specific, reviewed reason and must never satisfy a mandatory release gate. Do not report total production readiness unless every mandatory gate per language passes.

Current main at implementation start: no legal source admission entries, `manifest.json.packs=[]`, and `version.json.release_status=BLOCKED_DEPENDENCY`. Consequently there is no real pack SHA, source receipt, publication run ID, last-known-good archive or app-install receipt to assert. These remain blockers, not simulated successes.

## Ownership, dependencies, and limitations

Adapters reuse current GHA-08 coverage, GHA-06 release, PR #76 SQLite strict conformance, and the canonical ledger. Open PRs #90, #91, #102, #103 and #41 are **not imported** as merged contracts and their write scopes remain untouched. The pre-publication acceptance receipt is not an alternate public manifest authority.

The public Actions workflow runs stdlib Python and OpenSSL on a standard Ubuntu runner, with read-only permissions, no new secret, no cache and no publication. It produces a one-day *diagnostic* coverage artifact. No production-content worker can be dispatched from the present queue (`registry_validate` and `admission_partition_verify` only). Do not invent run IDs or schedule idle workers.

Outstanding production-only gates include: verified and licensed corpora for each language, true language-specific educational QA, real exact-byte candidates, live Workflow run receipt validation, publisher key trust provisioning, immutable published history and Last-Known-Good custody, update installation verification and private Flutter consumer validation. A public success status cannot replace these.