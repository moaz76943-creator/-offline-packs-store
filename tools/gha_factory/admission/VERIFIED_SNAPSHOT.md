# Verified snapshot admission (opt-in)

DEUTSCH-EXEC-04: additive repair for Issues #71 and #65. The existing pipeline
accepts a source fixture with only a reviewer URL, and iterates an unbounded
JSONL line before checking its length. This entry point requires hashed local
review evidence and copies bounded bytes before invoking the existing adapter.
It neither supplies a legal decision nor authenticates a reviewer cryptographically.

Run from repository root:

```sh
python -m tools.gha_factory.admission.verified_snapshot \
  --repo-root . --ledger-source-id OWNER_REVIEWED_ID \
  --input REVIEWED_ARTIFACT_PATH --out NEW_OUTPUT_DIRECTORY \
  --language de --dataset-version OWNER_REVIEWED_VERSION
```

The decision URL must be an issue or pull request on
`github.com/moaz76943-creator/-offline-packs-store`. Notice text is scanned by
the shared `legal.ledger.license_notice` module: real CC0 wordings are
recognized, a public-domain dedication does not conflict with CC0, and
restricted-license identifiers (not the bare words "Non-Commercial") still
conflict. A separate, owner-reviewed
`legal/ledger/review_snapshots/<source_id>.json` companion descriptor is required:

```json
{
  "source_id": "OWNER_REVIEWED_ID",
  "dataset_version": "OWNER_REVIEWED_VERSION",
  "source_sha256": "ACTUAL_SOURCE_SHA256",
  "license_evidence_sha256": "ACTUAL_LICENSE_NOTICE_SHA256",
  "reviewer": "INDEPENDENT_REVIEWER",
  "decision_url": "https://github.com/moaz76943-creator/-offline-packs-store/issues/179#issuecomment-1",
  "evidence_path": "legal/ledger/evidence/owner-review.txt",
  "evidence_sha256": "ACTUAL_REVIEW_FILE_SHA256"
}
```

This is a format illustration, not a valid source record. Never substitute guessed
hashes, auto-approve a source, or copy restricted evidence into the public repo.
The six identity fields must equal the selected ledger source. Actual source,
rights notice and review decision bytes must match their SHA256 values. The source
must already have explicit independent APPROVED_FOR_REDISTRIBUTION status.

Limits: source 256 MiB; ledger, registry, descriptor and each evidence file 1 MiB;
JSONL line 1 MiB. Larger archives are rejected without extraction; this adapter
only admits uncompressed wiktextract JSONL. Use separately reviewed immutable
shards for larger corpora, never relabel compressed archives as JSONL. Temporary
snapshots are removed after success/failure. Copy uses bounded reads and rejects
nonregular files and symlink components; a trusted local filesystem is required
(intermediate-directory rename races are outside this guard's sandbox guarantees).

Notice scanning is deliberately conservative. Unknown text, recognized NC/rights
restrictions and conflicting recognized markers are rejected even when their
hashes match. It is neither a general legal classifier nor proof of an original
rightsholder's authority. Ambiguous or mixed notices need human reconciliation.

Live investigation: main 7a5a554b7248ec6baa610ba443b747c7643ba9b9 has zero ledger
sources and no real approved source/license/review snapshot to hash. Issue #71 and
the official PanLex notice (https://panlex.org/license/, checked 2026-10-14) conflict
with the older CC0 candidate metadata outside this scope: official notice states
CC BY-NC-SA 4.0 and commercial use requires written permission. PanLex stays
BLOCKED_SOURCE; no candidate metadata is promoted or rewritten here.

Ownership: PR #178 owns pipeline.py and test_pipeline.py (plus legacy legal gate
files). This patch adds only verified_snapshot.py, test_verified_snapshot.py and
this document. All fetched PR refs were checked for those paths, with no overlap.
The legacy entry point and CI remain unchanged. Adoption must be coordinated with
#178's owner; Until then existing callers retain their existing behavior. #65's
production worker integration remains a separate dependency. No production pack,
source approval, manifest write, queue dispatch or hosted Actions run is made.

Validation:

```sh
python -m unittest discover -s tests/gha_factory/admission -v
python -m unittest discover -s legal/ledger -v
```

Fixtures are synthetic test data only and are never entered in the source ledger.
