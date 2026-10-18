"""Classify open PRs and squash-merge one that is already up to date and green.

GitHub's GITHUB_TOKEN cannot push a merge commit and then retrigger the required
pull_request check public-pr-merge-gate. This tool therefore does not push.
Updating a behind branch stays a signed merge commit from a normal git remote.
"""
import argparse
import json
import re
import subprocess

SKIP = re.compile(r"\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]", re.IGNORECASE)
SKIP_TRAILER = re.compile(r"(?im)^skip-checks\s*:\s*true\s*$")
FAILURES = {"FAILURE", "CANCELLED", "TIMED_OUT", "failure", "cancelled", "timed_out"}
PENDING = {"", "PENDING", "QUEUED", "IN_PROGRESS", "pending", "queued", "in_progress", None}

LABELS = {
    "behind": "blocked:behind",
    "gate": "blocked:gate",
    "threads": "blocked:threads",
    "conflict": "blocked:conflict",
    "draft": "blocked:draft",
    "unstable": "blocked:unstable",
}


def sanitize_subject(title, number):
    """Squash title with no CI-skip instruction."""
    cleaned = SKIP.sub("", title or "")
    cleaned = SKIP_TRAILER.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    if not cleaned:
        cleaned = f"PR {number}"
    marker = f"(#{number})"
    if marker not in cleaned and f"#{number}" not in cleaned:
        cleaned = f"{cleaned} {marker}"
    return cleaned[:240]


def _check_name(check):
    return check.get("name") or check.get("context") or ""


def _conclusion(check):
    return check.get("conclusion") or check.get("state")


def classify(pr):
    """Return ready, unknown, or a blocker key from a gh pr view JSON object."""
    if pr.get("isDraft") or pr.get("state") == "DRAFT":
        return "draft"
    state = pr.get("mergeStateStatus") or ""
    if state in {"DIRTY", "CONFLICTING"} or pr.get("mergeable") == "CONFLICTING":
        return "conflict"
    checks = pr.get("statusCheckRollup") or []
    gate = next((c for c in checks if _check_name(c) == "public-pr-merge-gate"), None)
    gate_state = _conclusion(gate) if gate else None
    failing = [c for c in checks if _conclusion(c) in FAILURES]
    pending = [c for c in checks if _conclusion(c) in PENDING or (c.get("status") in PENDING)]
    if gate_state in FAILURES:
        return "gate"
    if failing:
        return "unstable"
    if state == "BEHIND":
        return "behind"
    if state == "BLOCKED":
        return "threads"
    if state == "CLEAN" and gate_state == "SUCCESS" and not pending and not failing:
        return "ready"
    return "unknown"


def label_for(kind):
    return LABELS.get(kind)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Label blocked PRs and squash-merge one ready PR")
    parser.add_argument("--repo", default="moaz76943-creator/-offline-packs-store")
    parser.add_argument("--merge-one", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    listed = subprocess.check_output(
        ["gh", "pr", "list", "--repo", args.repo, "--state", "open", "--limit", "80",
         "--json", "number,title,isDraft,mergeStateStatus,headRefName"],
        text=True,
    )
    numbers = [item["number"] for item in json.loads(listed)]
    merged = None
    for number in numbers:
        view = json.loads(subprocess.check_output(
            ["gh", "pr", "view", str(number), "--repo", args.repo,
             "--json", "number,title,isDraft,state,mergeStateStatus,mergeable,statusCheckRollup"],
            text=True,
        ))
        kind = classify(view)
        print(f"#{number} {kind}")
        if args.dry_run:
            continue
        wanted = label_for(kind)
        for label in LABELS.values():
            if label == wanted:
                continue
            subprocess.call(["gh", "pr", "edit", str(number), "--repo", args.repo, "--remove-label", label],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wanted:
            subprocess.call(["gh", "label", "create", wanted, "--repo", args.repo, "--color", "B60205",
                             "--description", wanted], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call(["gh", "pr", "edit", str(number), "--repo", args.repo, "--add-label", wanted])
        elif kind == "ready" and args.merge_one and merged is None:
            subject = sanitize_subject(view["title"], number)
            if SKIP.search(subject) or SKIP_TRAILER.search(subject):
                raise SystemExit(f"refusing skip directive in squash subject for #{number}")
            subprocess.check_call([
                "gh", "pr", "merge", str(number), "--repo", args.repo, "--squash",
                "--subject", subject, "--body", f"Squash merge of #{number}.",
            ])
            merged = number
    if args.merge_one:
        print(f"merged={merged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
