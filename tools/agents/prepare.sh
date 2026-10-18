#!/usr/bin/env bash
# Overlay the last committed agent snapshot. A missing branch is not an error.
set -u
git fetch origin agents/data || true
if git rev-parse --verify origin/agents/data >/dev/null 2>&1; then
  git checkout origin/agents/data -- state data STATUS.md || true
fi
mkdir -p /tmp/agent-out
exit 0
