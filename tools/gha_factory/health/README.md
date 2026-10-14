# DEUTSCH-IMPROVE-06 — queue health (read-only)

This is an advisory inspection tool, **not a second controller**, worker, or queue. It does not mutate Issues, leases, receipts, workflows, or packs.

From the public repository root, with an authenticated `gh` CLI:

```sh
python3 tools/gha_factory/health/check.py --output "$HOME/gha_queue_health.json"
python3 -m unittest discover -s tests/gha_factory/health -p 'test_*.py' -v
```

For offline fixtures use `--snapshot file.json` containing `issues` and `workflow_runs`. Issues must be from the repository owner, use `[GHA-TASK] ...` and a `gha-task-v1` envelope. An expired lease yields `REVIEW`, **never proof a worker died**. Unavailable API yields `UNKNOWN`. Snapshot is not independent validation of receipt bytes or GitHub runner status.

At the pinned main baseline, the canonical dispatcher only admits `registry_validate` and `admission_partition_verify`; this tool must not be interpreted as a lexical/examples/release processor or as source release approval. Refer to `tools/gha_factory/dispatcher/README.md` and Issues #65/#69. No paid runner and no automatic recovery.
