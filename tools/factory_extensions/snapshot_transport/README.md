# Complementary snapshot transport contract v1

Scope: tools/factory_extensions/snapshot_transport/**, tests/factory_extensions/snapshot_transport/**, and .github/workflows/snapshot_transport_qa.yml only.

## Production status — 2026-10-13

- Live main Route 05 legal/ledger/sources.json has sources: [] — BLOCKED_SOURCE.
- GHA-02 supports registry_validate and admission_partition_verify only. Snapshot leases and handoff are BLOCKED_DEPENDENCY_GHA02.
- PR #67 owns source-snapshot processing. This independent library does not touch or fork those files.
- No production corpus downloads, release publication, pack modification or queue mutations.

## Interfaces

- approved_source(root, source_id, version, language, url, sha256, size, hosts): fail-closed exact Route 05/GHA-01 registry and source-rights evidence check. Independently reviewed allowed hosts and byte bounds must be supplied by trusted orchestration. This code never grants legal rights.
- download(source, target): optional, not wired to CLI or CI. DNS-global-only public IPs with pinned TLS SNI/hostname, no redirects, bounded range resume, strict content length, full SHA-256, atomic promotion. Partial downloads are never trusted as sources.
- stage(source, verified_input, persistent_store, fmt, shard_rows): streamed strict UTF-8 JSONL, gzip, bz2 or xz. Reject duplicate JSON keys, invalid encoding/framing, wrong language/source/version and oversized lines/expansion. Maximum 10,000 rows per shard.
- shards/<sha256>.jsonl: immutable SHA-deduplicated bytes; checkpoints/<identity>/<index>.json: write-once source-specific provenance; manifests/<identity>.json: deterministic complete STAGED_ONLY manifest with source/language/version, source and shard SHA, counts and schema. Replay validates entire source and existing checkpoint/blob digests, without rewriting committed content.
- Operational report records measured input bytes, CPU/wall time, disk free, retry state separately from deterministic manifests.

**Storage blocker:** Public GitHub Actions runners are ephemeral. Cross-run replay is durable only when an independently approved, authenticated, persistent immutable filesystem backend is mounted at persistent_store. This PR DOES NOT provision or authorize that backend. Therefore persistent_backend_verified remains false. Production wiring requires both Route 05 source/storage rights and GHA-02 lease/checkpoint ownership review.

## Verified GitHub storage facts, 2026-10-13

GitHub Releases permit at most 1,000 assets per release, each asset under 2 GiB; no limit on total release size or bandwidth is documented. This does NOT authorize unrestricted corpus redistribution, permanent asset lifecycle or unlimited zero-cost usage:
https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases

GitHub Actions artifacts/logs have 90-day default retention, public configurable 1–90 days. They are not a permanent source store:
https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features/managing-github-actions-settings-for-a-repository

Synthetic QA: python3 -m unittest discover -s tests/factory_extensions/snapshot_transport -p 'test_*.py' -v
Public standard Ubuntu; QA timeout 12 minutes; no external source traffic or production artifacts. Future independent hosted workers remain limited to three and bounded below six hours.
