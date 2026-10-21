#!/usr/bin/env bash
# Overlay the committed agent snapshot for readers without staging it as a commit.
set -euo pipefail
branch="agents/data"
git fetch origin "$branch"
git restore --source="origin/$branch" --worktree -- state data STATUS.md
mkdir -p "${AGENT_OUT:-/tmp/agent-out}"
