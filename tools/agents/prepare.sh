#!/usr/bin/env bash
# Overlay the committed agent snapshot for readers without staging it as a commit.
# A missing agents/data ref is recovered from state/agents/snapshot-ref.json or
# skipped. It must not fail the fleet.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=snapshot_ref.sh
source "$here/snapshot_ref.sh"
pointer="$SNAPSHOT_POINTER"
saved=""
if [ -f "$pointer" ]; then
  saved="$(mktemp)"
  cp "$pointer" "$saved"
fi
rev="$(snapshot_resolve .)"
if [ -n "$rev" ]; then
  git restore --source="$rev" --worktree -- state data STATUS.md || {
    echo "snapshot restore from ${rev} failed; continuing without it" >&2
  }
fi
if [ -n "$saved" ] && [ ! -f "$pointer" ]; then
  mkdir -p "$(dirname "$pointer")"
  cp "$saved" "$pointer"
fi
if [ -n "$saved" ]; then
  rm -f "$saved"
fi
# ${TMPDIR:-/tmp} keeps the CI default while letting a sandboxed runner
# redirect the output root when /tmp itself is not writable.
mkdir -p "${AGENT_OUT:-${TMPDIR:-/tmp}/agent-out}"
