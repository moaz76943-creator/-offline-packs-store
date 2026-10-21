#!/usr/bin/env bash
# Update STATUS, the repair cursor, source-decision issues, and one rolling PR.
# Does not dispatch another workflow and does not edit the ledger or packs/.
set -euo pipefail

: "${DUMP_DATE:?}"
: "${SLOT:?}"
: "${MAX_BYTES:?}"
: "${FETCH_RESULT:?}"
: "${BUILD_RESULT:?}"

state="dist/state/language-production"
mkdir -p "$state" dist/candidates/language-production

success=false
signature=""
if [ "$FETCH_RESULT" = "success" ] && [ "$BUILD_RESULT" = "success" ]; then
  success=true
elif [ "$FETCH_RESULT" != "success" ]; then
  signature="curl http 206"
else
  signature="gzip"
fi

if [ "$success" = "true" ]; then
  repair_json="$(python3 -m tools.language_production.cli repair --state "$state/repair.json" --success)"
else
  repair_json="$(python3 -m tools.language_production.cli repair --state "$state/repair.json" --signature "$signature")"
fi
advance="$(python3 -c 'import json,sys; print("true" if json.loads(sys.argv[1])["advance"] else "false")' "$repair_json")"

slice="dist/candidates/language-production/slice"
downloaded="0"
wrapped_flag=()
if [ -f "$slice/downloaded_bytes" ]; then
  downloaded="$(tr -d '[:space:]' < "$slice/downloaded_bytes")"
fi
if [ -f "$slice/wrapped" ] && [ "$(tr -d '[:space:]' < "$slice/wrapped")" = "true" ]; then
  wrapped_flag=(--wrapped)
fi
if [ "$advance" = "true" ] && [[ "$downloaded" =~ ^[0-9]+$ ]] && [ "$downloaded" -gt 0 ]; then
  python3 -m tools.language_production.cli advance \
    --cursor "$state/cursor.json" \
    --dump-date "$DUMP_DATE" \
    --downloaded-bytes "$downloaded" \
    "${wrapped_flag[@]}"
else
  echo "cursor left in place"
fi

shopt -s nullglob
reports=(dist/candidates/language-production/overlays/*/*.summary.json)
status_tmp="$(mktemp)"
if [ "${#reports[@]}" -gt 0 ]; then
  python3 -m tools.language_production.cli status \
    --reports "${reports[@]}" \
    --output "$status_tmp" \
    --dump-date "$DUMP_DATE" \
    --slot "$SLOT" \
    --slice-bytes "$MAX_BYTES"
fi

if [ -n "${GH_TOKEN:-}" ]; then
  titles="$(mktemp)"
  if gh issue list --state open --limit 100 --json title --jq '[.[].title]' > "$titles"; then
    missing="$(python3 -m tools.language_production.cli missing-issues --titles "$titles")"
    python3 - "$missing" <<'PY'
import json, subprocess, sys
missing = json.loads(sys.argv[1])
body = """This issue records the owner decision for language production.

Only moaz76943-creator can approve it. Approval is a comment whose own line is:

decision: approve

Until that comment exists, the pipeline does not add a ledger row and does not publish sentences.
"""
for title in missing:
    subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=False)
PY
  fi
fi

# Merge yesterday's rolling PR only when its checks are already green.
# Today's commit is pushed afterwards, so this run cannot merge itself.
if [ -n "${GH_TOKEN:-}" ] && [ "${HALT:-}" != "true" ]; then
  if gh pr view language-production/rolling --json headRefOid,statusCheckRollup > /tmp/rolling-pr.json 2>/dev/null; then
    python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/rolling-pr.json").read_text(encoding="utf-8"))
rollup = payload.get("statusCheckRollup") or []
checks = [{
    "name": item.get("name") or item.get("context"),
    "status": item.get("status") or "",
    "conclusion": item.get("conclusion") or "",
} for item in rollup]
Path("/tmp/checks-flat.json").write_text(json.dumps(checks), encoding="utf-8")
PY
    number="$(gh pr view language-production/rolling --json number --jq .number)"
    owner="${GITHUB_REPOSITORY%%/*}"
    repo="${GITHUB_REPOSITORY#*/}"
    threads="$(gh api graphql -f owner="$owner" -f name="$repo" -F number="$number" -f query='query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved}}}}}' --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false)] | length' || echo 1)"
    decision="$(python3 -m tools.language_production.cli merge-decision --checks /tmp/checks-flat.json --unresolved-threads "$threads" --allow-skip || true)"
    merge="$(python3 -c 'import json,sys; print("true" if json.loads(sys.argv[1]).get("merge") else "false")' "$decision" || echo false)"
    if [ "$merge" = "true" ]; then
      gh pr merge language-production/rolling --squash || echo "merge refused; leaving the pull request open"
      git fetch origin main
    else
      echo "not merging: $decision"
    fi
  fi
fi

git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git config user.name "github-actions[bot]"
if git fetch origin language-production/rolling && git checkout -B language-production/rolling origin/language-production/rolling; then
  git merge --no-edit origin/main || git merge --abort
else
  git checkout -B language-production/rolling origin/main
fi

if [ -s "$status_tmp" ]; then
  cp "$status_tmp" STATUS.md
fi
if [ -d dist/candidates/language-production/overlays ]; then
  find dist/candidates/language-production/overlays -type f \( -name '*.sqlite' -o -name '*.concepts.json' -o -name '*.summary.json' \) -print0 |
    while IFS= read -r -d '' file; do
      cp "$file" "dist/candidates/language-production/$(basename "$file")"
    done
fi
rm -rf dist/candidates/language-production/slice dist/candidates/language-production/overlays

git add -- STATUS.md dist/candidates/language-production || true
if git diff --cached --name-only | grep -E '^(packs/|legal/ledger/sources\.json|manifest\.json)$'; then
  echo "refusing to publish packs, the ledger, or the manifest" >&2
  exit 1
fi
if git diff --cached --quiet; then
  echo "no candidate changes"
else
  git commit -m "chore(language-production): refresh candidate overlays"
  git push origin language-production/rolling
fi
if [ -n "${GH_TOKEN:-}" ]; then
  if ! gh pr view language-production/rolling --json number >/dev/null 2>&1; then
    gh pr create --base main --head language-production/rolling \
      --title "Language production candidates" \
      --body "Rolling unpublished Wikidata lexeme overlays. publication_approved is false. Sentences stay empty until the owner approves the Tatoeba decision issue."
  fi
fi
