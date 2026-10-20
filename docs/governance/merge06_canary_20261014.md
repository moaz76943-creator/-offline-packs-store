# DEUTSCH-MERGE-06: non-sensitive governance canary

This document exercises the existing public pull-request protection workflow without changing production logic or repository settings.

- Canonical integration branch: `main`.
- Source baseline (observed before this canary): `1f9a4b04be8b757a307f5f7e9d1e851a03174bca`.
- Scope: this one Markdown file only.
- Expected: PR opens in Draft, transitions to Ready, required `public-pr-merge-gate` runs, and the ruleset continues to require a genuinely independent human approval.
- Never treat a skipped, pending, absent, or comment-only review as approval or successful CI.
- This canary must remain unmerged until the owner and integration coordinator confirm all requirements.
- No workflow, token, secret, manifest, pack, external app, or production code is changed.
