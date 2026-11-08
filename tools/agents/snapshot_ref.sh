#!/usr/bin/env bash
# Resolve the shared agents/data checkpoint without inventing a new history.
# Sourced by prepare.sh and publish.sh. A missing branch is recovered from the
# sha recorded on main, or left absent. This never force-updates a ref.
SNAPSHOT_BRANCH="agents/data"
SNAPSHOT_POINTER="state/agents/snapshot-ref.json"

snapshot_pointer_sha() {
  local file="$1"
  python3 - "$file" <<'PY'
import json
import sys
path = sys.argv[1]
try:
    data = json.load(open(path, encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)
sha = data.get("sha") if isinstance(data, dict) else ""
if isinstance(sha, str) and len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
    print(sha)
PY
}

# Print a revision prepare/publish can read: "origin/<branch>" when that ref
# exists (or was just created), or the recorded sha when only the object is
# available. Print nothing when there is no recoverable snapshot.
snapshot_resolve() {
  local repo="${1:-.}"
  if git -C "$repo" fetch origin "$SNAPSHOT_BRANCH" >/dev/null 2>&1; then
    printf 'origin/%s\n' "$SNAPSHOT_BRANCH"
    return 0
  fi
  local sha
  sha="$(snapshot_pointer_sha "$repo/$SNAPSHOT_POINTER")"
  if [ -z "$sha" ]; then
    echo "agents/data is missing and ${SNAPSHOT_POINTER} has no sha; continuing without the snapshot" >&2
    return 0
  fi
  if ! git -C "$repo" fetch origin "$sha" >/dev/null 2>&1; then
    echo "agents/data is missing and recorded snapshot ${sha} cannot be fetched; continuing without it" >&2
    return 0
  fi
  # Create the absent ref at the recorded commit. A rejection is not retried
  # with force: either the branch appeared, or the update is not a fast-forward.
  if git -C "$repo" push origin "${sha}:refs/heads/${SNAPSHOT_BRANCH}" >/dev/null 2>&1 \
      && git -C "$repo" fetch origin "$SNAPSHOT_BRANCH" >/dev/null 2>&1; then
    printf 'origin/%s\n' "$SNAPSHOT_BRANCH"
    return 0
  fi
  if git -C "$repo" fetch origin "$SNAPSHOT_BRANCH" >/dev/null 2>&1; then
    printf 'origin/%s\n' "$SNAPSHOT_BRANCH"
    return 0
  fi
  printf '%s\n' "$sha"
}
