#!/usr/bin/env bash
# Commit one agent's files to agents/data. No force push. A merge conflict stops this agent only.
set -u
name="${1:?agent name}"
out="${AGENT_OUT:-/tmp/agent-out}"
branch="agents/data"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git config user.name "github-actions[bot]"
if [ ! -d "$out" ]; then
  echo "no agent output"
  exit 0
fi
stage="$(mktemp -d)"
cp -a "$out"/. "$stage"/
git fetch origin "$branch" || true
if git rev-parse --verify "origin/$branch" >/dev/null 2>&1; then
  git checkout -B "$branch" "origin/$branch"
else
  git checkout -B "$branch"
fi
mkdir -p state/agents data/agents
if [ -d "$stage/state" ]; then
  cp -a "$stage/state"/. state/
fi
if [ -d "$stage/data" ]; then
  mkdir -p data
  cp -a "$stage/data"/. data/
fi
if [ -f "$stage/STATUS.md" ]; then
  cp "$stage/STATUS.md" STATUS.md
fi
git add -- state data STATUS.md || true
if git diff --cached --name-only | grep -E '^(packs/|legal/ledger/sources\.json|manifest\.json)$'; then
  echo "refusing to publish packs, the ledger, or the manifest" >&2
  exit 1
fi
if git diff --cached --quiet; then
  echo "nothing to publish for ${name}"
  exit 0
fi
git commit -m "chore(agents): checkpoint ${name}"
# One integration of disjoint per-agent files. A second rejection is a shared-path
# conflict: the health agent records that signature instead of looping the push.
if git push origin "$branch"; then
  exit 0
fi
git fetch origin "$branch" || exit 1
git merge --no-edit "origin/$branch" || exit 1
git push origin "$branch"
