# DEUTSCH-IMPROVE-02 — Optional cross-run ScopeGuard companion

Existing private PR #118 and #125 both implement a local `fcntl`-guarded TaskLedger under `tools/agent_contract/guard.py`. Their ledgers coordinate processes that share a filesystem, not independent phones, GitHub runners and Jules environments. This module complements (does not replace) those guards with an optional Git fast-forward compare-and-swap lease protocol.

**Status: code proposal / Draft only; NOT activated.** This PR does not create a live lease branch, start jobs, configure CI, claim files, merge content or force Jules to participate. Until every writer calls the protocol and a real integration gate enforces it, repository-wide single-writer safety is **not guaranteed**.

## Storage and atomic protocol

The canonical ledger backend is an explicitly chosen **private** repository, never the public content repository. The file is `tools/coordination/leases.json` on a separate `coordination/leases` branch. Each modification constructs a Git blob/tree/commit with the **current ledger commit as the parent**, then attempts a non-force ref update. Concurrent divergent children of the same parent cannot both fast-forward. Retries are bounded; history is never reset.

A claim records TASK_ID, repository, base branch, BASE_HEAD_SHA, claimed file paths, agent owner, actor, lease ID (unique per generation), TTL, expiry, PR number, state, and optional GitHub Actions run ID/attempt. Local status events are bounded to the latest 128; Git history retains prior transitions. `READ_ONLY` is returned without writes on conflict.

Patterns allow either a literal path or terminal `/**`; overlapping ancestor/subtree scopes conflict within the same repository regardless of branch. Malformed paths and traversal are rejected. `verify-pr` checks both old and new rename paths, complete changed-file count, PR identity and exact head SHA, base HEAD and live unexpired ownership.

Renew/release require matching owner and lease ID. An expired claim still blocks other writers until the owner releases it or `recover` confirms the recorded GitHub Actions run/attempt has actually terminated. Expiry alone, or an unverified text assertion, never grants recovery. This prevents old lease-ID ABA release/renewal. Non-Actions agents require owner intervention for abandoned claims. Ledger snapshots fetch file bytes using the immutable Git commit SHA, not a moving branch ref, to avoid mixed-version reads when concurrent writers advance the lease branch.

**Important limitations:** a caller may declare an agent name but multiple agents using the same GitHub identity cannot be distinguished cryptographically. Protect the private ledger branch and restrict write access before operational use. `AUTHORIZED_SCOPE_ONLY` does not establish CI success, security, rights approval or merge eligibility. A raw Git push or a Jules job that ignores this guard is not blocked. The existing public merge coordinator remains the only potential merge authority.

## Focused local verification

Run from the repository root:

    python3 -m unittest discover -s tests/coordination -p 'test_*.py' -q

23 deterministic tests cover 8-way concurrent claims, cross-repo independence, prefix/path safeguards, move/rename preflight, HEAD movement, renew/release fencing, post-expiry recovery with independently terminated run ID/attempt, ABA, and competing Git commits. Real GitHub CAS + Jules integration remains **NOT_RUN**; no live private ledger branch was initialized.

## Explicit bootstrap after approval (not executed)

    python3 -m tools.coordination.cli --ledger-repo moaz76943-creator/deutsch-build bootstrap

Read-only inspection after bootstrap:

    python3 -m tools.coordination.cli --ledger-repo moaz76943-creator/deutsch-build inspect --repo moaz76943-creator/-offline-packs-store --branch main --path 'tools/coordination/**'

Claim after checking the live base SHA:

    python3 -m tools.coordination.cli --ledger-repo moaz76943-creator/deutsch-build claim --task DEUTSCH-EXAMPLE --owner example-agent --repo moaz76943-creator/-offline-packs-store --branch main --sha '<LIVE_40_CHARACTER_SHA>' --path 'tools/coordination/**' --ttl 900

Save the returned lease_id and pass it to `renew`, `release`, and `verify-pr`; exit 2 means conflict/unknown/blocked. Other tasks require no new billing.

## Outstanding gates (must be met before activation)

1. Resolve the competing private PR #118 and #125 implementations under the existing guard's owner; do not overwrite Jules.
2. Integrate opt-in acquisition/renewal into **all** writers and workers, not merely this CLI.
3. Attach exact-head PR scope verification to the canonical merge/PR checks, without introducing a second writer (public PR #165 remains Draft).
4. Test authenticated, independent clients and private branch protections before activating a production ledger; a bounded isolated GitHub CAS probe has been performed (see below), but all-worker integration remains NOT_RUN.
5. Keep unpublished external agent reservations and non-Actions recovery **UNKNOWN/BLOCKED** until independently verified.

Neither this new tool nor an Issue/PR comment should be treated as an authoritative claim unless the coordinating branch and GitHub integration have been verified.

## Live GitHub CAS evidence — 2026-10-14 (isolated private scratch)

A **non-production** branch `scratch/improve02-cas-20261014` in the private repo was created from private staging HEAD `8dee49f1ab2a82e023fe6f93067fa980d8471bb8`. The only new tracked file was `tools/coordination/live_cas_probe.json`, containing synthetic fixture values; no learner data, tokens, or Jules files were touched.

- Fixture parent commit: `17baf3bfab98d27f0eb2997d03b46cd8556690fc`.
- Competing same-parent commits: A=`dc37503e56fef7eece5c71302f306fb0143773bc`, B=`759c1a6594c75aeb1bb73348f0eacb87cb1be996`. Each changed only the scoped test file.
- A non-force ref update succeeded. The simultaneous B request returned an **ambiguous GraphQL error** and is **not** treated as an authoritative conflict reason.
- A separately repeated B update with `force=false`, after A became HEAD, was independently rejected by GitHub REST: **HTTP 422, `Update is not a fast forward`**.
- Final scratch HEAD: `dc37503e56fef7eece5c71302f306fb0143773bc`; downloaded fixture state identifies A. The private development branch was not moved.

This validates real GitHub **stale non-fast-forward rejection** for competing commits, not two independently authenticated clients, not reliable branch protection enforcement, and not global adoption by agents. **Operational activation remains BLOCKED** pending owner arbitration of private PRs #118/#125, protected storage and a mandatory all-writer preflight.
