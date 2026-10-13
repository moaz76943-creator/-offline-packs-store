# Public SQLite v2 security-fuzz QA

This harness is **test-only** and imports the existing GHA-06 release validator and its
synthetic fixture. It neither generates production packs nor edits a manifest.
It uses the public three-member Route 07 gzip envelope, not a competing format.

Run from repository root:

\`\`\`bash
python3 -m unittest discover -s tests/gha_factory/security_fuzz -p 'test_*.py' -v
python3 tools/gha_factory/security_fuzz/harness.py --family envelope --seed 20261013 --max-cases 48
\`\`\`

There are 39 deterministic cases in five families: envelope, SQLite/FTS5,
provenance, public-only Ed25519 verification, and staging/rollback. All mutation
targets and rollback sentinels are temporary, synthetic public fixture data.
Cases are bounded; memory, CPU, file-size and runtime limits are applied by
the read-only Ubuntu Actions workflow. Weekly schedule and manual dispatch
are supported, with max two parallel jobs and one-day compact JSON evidence.

Each case emits PASS, FAIL, CLOSED, or SECURITY_FINDING. The last is a
**diagnostic signal**, not a pass on a security requirement or authorization
to publish. Findings represent behaviors accepted by the low-level archive
inspector that require additional producer/consumer policy, including
duplicate/noncanonical JSON and untrusted readiness/signature assertions.
The source gate in GHA-06's build path is independently tested; accepting an
extra JSON property alone does not prove a release-path exploit. The report
always says publication_approved=false.

Known dependencies:
- GHA-06 candidate API: imported from the existing public main branch.
- GHA-02 fuzz job type: not yet wired; use isolated schedule/manual dispatch.
- Real approved source candidates: blocked until the licensing ledger grants
  admissible source provenance. No corpus, signing keys, or production pack
  are ever emitted by these tests.
- GitHub-hosted test success must be confirmed before merging. A PR with
  skipped CI alone is not proof of a passing test run.

Any newly verified defect should receive a named, deterministic regression
mutation in the appropriate family; fixes to canonical release validators
remain outside this branch's exclusive write scope.
