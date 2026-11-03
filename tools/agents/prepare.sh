#!/usr/bin/env bash
# Overlay the committed agent snapshot for readers without staging it as a commit.
set -euo pipefail
branch="agents/data"
git fetch origin "$branch"
git restore --source="origin/$branch" --worktree -- state data STATUS.md
# ${TMPDIR:-/tmp} keeps the CI default while letting a sandboxed runner
# redirect the output root when /tmp itself is not writable.
mkdir -p "${AGENT_OUT:-${TMPDIR:-/tmp}/agent-out}"
