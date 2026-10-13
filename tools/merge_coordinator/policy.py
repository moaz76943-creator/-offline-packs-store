"""Deterministic, conservative PR integration policy (stdlib only).

Status is evidence-based and cannot grant privileges or waive CI.
"""
import re
from collections import defaultdict

REQUIRED_GATE = "public-pr-merge-gate"
SKIP = re.compile(r"\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|(?m:^skip-checks\s*:\s*true\s*$)", re.I)
# A replacement relationship records competing scope, never grants merge approval.
REPLACED_BY = {77: 137, 84: 139, 95: 136, 120: 144, 79: 132}
COMPETING = ({5, 13}, {18, 20, 21}, {100, 101})
AUTO_APPROVAL_LABEL = "merge-safe-approved"


def skip_message(message):
    return bool(SKIP.search(message or ""))


def risk_for(paths):
    if not paths:
        return "UNKNOWN"
    if all((p.startswith("docs/") and p.endswith(".md")) or p.endswith("/README.md")
           for p in paths):
        return "DOCS"
    if any(p.startswith(("legal/", ".github/", "tools/release", "tools/provenance",
                        "tools/pack_", "tools/gha_factory/", "community/",
                        "catalog/", "standards/")) or
           p in {"manifest.json", "version.json"} for p in paths):
        return "CRITICAL"
    return "CODE"


def conflicts(files_by_number):
    owners = defaultdict(set)
    for number, paths in files_by_number.items():
        for path in paths:
            owners[path].add(number)
    overlaps = defaultdict(set)
    for numbers in owners.values():
        if len(numbers) > 1:
            for number in numbers:
                overlaps[number].update(numbers - {number})
    return {n: sorted(v) for n, v in overlaps.items()}


def state_for(pr, paths, peers, available_numbers):
    number = int(pr["number"])
    labels = {label["name"] for label in pr.get("labels", [])}
    risk = risk_for(paths)
    report = {"number": number, "title": pr.get("title", ""), "url": pr.get("html_url", ""),
              "head_sha": pr["head"]["sha"], "draft": bool(pr.get("draft")), "risk": risk,
              "overlap_with": sorted(peers), "status": None, "reason": ""}
    def stop(status, reason):
        report.update(status=status, reason=reason)
        return report
    if number in REPLACED_BY and REPLACED_BY[number] in available_numbers:
        return stop("SUPERSEDED_REVIEW", f"Replacement #{REPLACED_BY[number]} requires independent verification")
    for group in COMPETING:
        if number in group and len(group & available_numbers) > 1:
            return stop("COMPETING_REVIEW", f"Competing alternatives: {sorted(group & available_numbers)}")
    if pr.get("draft"):
        return stop("DRAFT", "Author has not marked this PR ready for review")
    if peers:
        return stop("OVERLAPPING_REVIEW", "Overlapping open PR file scope requires canonical owner decision")
    if risk == "UNKNOWN":
        return stop("UNVERIFIED", "Cannot validate complete changed-file inventory")
    if risk != "DOCS" and AUTO_APPROVAL_LABEL not in labels:
        return stop("OWNER_APPROVAL_REQUIRED", "Code or security-sensitive change lacks explicit merge-safe-approved label")
    if risk == "CRITICAL":
        return stop("HUMAN_REVIEW", "Sensitive files require independent, exact-SHA review")
    return stop("CANDIDATE", "Requires live branch-protection, exact-SHA checks, review and base verification")


def checks_pass(checks, required=None):
    required = set(required or ()) | {REQUIRED_GATE}
    by_name = defaultdict(list)
    for check in checks:
        by_name[check.get("name")].append(check)
    for name in required:
        matched = by_name.get(name, ())
        if not matched or not any(c.get("status") == "completed" and
                                  c.get("conclusion") == "success" and
                                  c.get("app", {}).get("slug") == "github-actions"
                                  for c in matched):
            return False, f"Missing exact-SHA PASS from trusted Actions check {name}"
    for check in checks:
        if check.get("conclusion") in ("failure", "cancelled", "timed_out", "action_required"):
            return False, f"Failing check {check.get('name')}"
    return True, "All required trusted hosted checks passed"


def protection_is_enforced(branch, detail):
    if not branch.get("protected") or not isinstance(detail, dict):
        return False, "main is not protected; no automation may merge"
    required = detail.get("required_status_checks") or {}
    contexts = set(required.get("contexts") or [])
    contexts.update(c.get("context") for c in required.get("checks") or [])
    if not required.get("strict") or REQUIRED_GATE not in contexts:
        return False, "main must enforce strict up-to-date public-pr-merge-gate"
    admins = detail.get("enforce_admins") or {}
    if not admins.get("enabled"):
        return False, "main protection must include administrators"
    if not detail.get("required_pull_request_reviews"):
        return False, "main must require pull-request reviews"
    return True, "strict protection with admin and review enforcement"


def latest_approval(reviews, head_sha):
    # GitHub dismisses or updates approvals; latest submitted review per login wins.
    by_user = {}
    for r in sorted(reviews, key=lambda x: x.get("submitted_at") or ""):
        user = (r.get("user") or {}).get("login")
        if user and r.get("commit_id") == head_sha:
            by_user[user] = r.get("state")
    return any(state == "APPROVED" for state in by_user.values())
