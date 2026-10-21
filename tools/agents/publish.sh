#!/usr/bin/env bash
# Publish one agent's checkpoint from an isolated worktree; never rewrite shared HEAD.
set -euo pipefail
name="${1:?agent name}"
out="${AGENT_OUT:-/tmp/agent-out}"
branch="agents/data"
if [ ! -d "$out" ]; then
  echo "no agent output"
  exit 0
fi

stage="$(mktemp -d)"
checkout="$stage/worktree"
cleanup() {
  git worktree remove --force "$checkout" >/dev/null 2>&1 || true
  rm -rf "$stage"
}
trap cleanup EXIT
mkdir -p "$stage/output"
cp -a "$out"/. "$stage/output"/

# A failed fetch must not silently create a replacement for the shared branch.
git fetch origin "$branch"
git worktree add --detach "$checkout" "origin/$branch"
git -C "$checkout" config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git -C "$checkout" config user.name "github-actions[bot]"
if [ -d "$stage/output/state" ]; then
  mkdir -p "$checkout/state"
  cp -a "$stage/output/state"/. "$checkout/state"/
fi
if [ -d "$stage/output/data" ]; then
  mkdir -p "$checkout/data"
  cp -a "$stage/output/data"/. "$checkout/data"/
fi
if [ -f "$stage/output/STATUS.md" ]; then
  cp "$stage/output/STATUS.md" "$checkout/STATUS.md"
fi
git -C "$checkout" add -- state data STATUS.md
if git -C "$checkout" diff --cached --quiet; then
  echo "nothing to publish for ${name}"
  exit 0
fi
git -C "$checkout" commit -m "chore(agents): checkpoint ${name}"
if git -C "$checkout" push origin "HEAD:refs/heads/$branch"; then
  exit 0
fi
# One bounded retry for a concurrent disjoint-file update; conflicts fail closed.
git -C "$checkout" fetch origin "$branch"
git -C "$checkout" merge --no-edit "origin/$branch"
git -C "$checkout" push origin "HEAD:refs/heads/$branch"
