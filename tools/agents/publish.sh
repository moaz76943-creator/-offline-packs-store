#!/usr/bin/env bash
# Publish one agent's checkpoint from an isolated worktree; never rewrite shared HEAD.
# A missing agents/data ref is recreated at the sha recorded on main, or this
# publish is skipped. It never force-pushes and never starts a new root history.
set -euo pipefail
name="${1:?agent name}"
out="${AGENT_OUT:-/tmp/agent-out}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=snapshot_ref.sh
source "$here/snapshot_ref.sh"
branch="$SNAPSHOT_BRANCH"
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
rev="$(snapshot_resolve .)"
if [ "$rev" != "origin/$branch" ]; then
  echo "no recoverable ${branch} snapshot; skipping publish for ${name}"
  exit 0
fi
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
