#!/usr/bin/env python3
"""Bounded, serialized GitHub PR inventory and guarded squash-merge coordinator."""
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .policy import (REQUIRED_GATE, checks_pass, conflicts, latest_approval,
                    protection_is_enforced, skip_message, state_for)

REPO = "moaz76943-creator/-offline-packs-store"
LEDGER_TITLE = "[MERGE-CONTROL] Public PR decision ledger — automated inventory"
MAX_PRS = 300
MAX_FILES_PER_PR = 300
MAX_MERGES = 3


class ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(f"GitHub API {status}: {message[:250]}")


class GitHub:
    def __init__(self, token, repo=REPO):
        if repo != REPO or not token:
            raise ValueError("exact public repo and scoped GITHUB_TOKEN required")
        self.token, self.repo = token, repo

    def call(self, method, path, payload=None):
        if not path.startswith("/"):
            raise ValueError("relative API path required")
        url = "https://api.github.com/repos/" + self.repo + path
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "deutsch-public-merge-coordinator"}
        for attempt in range(3):
            req = Request(url, data=body, headers=headers, method=method)
            try:
                with urlopen(req, timeout=18) as response:
                    data = response.read(8_000_000)
                    return json.loads(data) if data else {}
            except HTTPError as exc:
                raw = exc.read(4096).decode("utf-8", "replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ApiError(exc.code, raw) from exc
            except (TimeoutError, URLError) as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise ApiError("NETWORK", str(exc)) from exc
        raise ApiError("RETRY", "exhausted")

    def get(self, path):
        return self.call("GET", path)

    def put(self, path, payload):
        return self.call("PUT", path, payload)

    def post(self, path, payload):
        return self.call("POST", path, payload)

    def patch(self, path, payload):
        return self.call("PATCH", path, payload)

    def pages(self, path):
        results = []
        for page in range(1, 6):
            suffix = "&" if "?" in path else "?"
            batch = self.get(f"{path}{suffix}per_page=100&page={page}")
            if isinstance(batch, dict) and "/check-runs" in path:
                batch = batch.get("check_runs")
            if not isinstance(batch, list):
                raise ApiError("SCHEMA", "expected paginated list")
            results.extend(batch)
            if len(batch) < 100:
                return results
        raise ApiError("LIMIT", "pagination exceeds bounded 500 records")


def inventory(api):
    branch = api.get("/branches/main")
    prs = api.pages("/pulls?state=open")
    if len(prs) > MAX_PRS:
        raise ApiError("CAP", "more than 300 PRs; refuse incomplete report")
    filenames = {}
    errors = {}
    def load(pr):
        number = pr["number"]
        rows = api.pages(f"/pulls/{number}/files")
        if len(rows) > MAX_FILES_PER_PR:
            raise ApiError("CAP", f"PR #{number} exceeds 300 files")
        return number, [item["filename"] for item in rows]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load, pr): pr["number"] for pr in prs}
        for future in as_completed(futures):
            number = futures[future]
            try:
                n, paths = future.result()
                filenames[n] = paths
            except (ApiError, KeyError, TypeError) as exc:
                errors[number] = str(exc)
    clashes = conflicts(filenames)
    available = {pr["number"] for pr in prs}
    items = []
    for pr in prs:
        n = pr["number"]
        if n in errors:
            items.append({"number": n, "title": pr["title"], "url": pr["html_url"],
                          "head_sha": pr["head"]["sha"], "draft": pr["draft"],
                          "risk": "UNKNOWN", "overlap_with": [], "status": "UNVERIFIED",
                          "reason": errors[n]})
        else:
            items.append(state_for(pr, filenames.get(n, []), clashes.get(n, []), available))
    items.sort(key=lambda item: item["number"])
    return {"repository": REPO, "main_sha": branch["commit"]["sha"],
            "main_protected": bool(branch["protected"]),
            "open_pr_count": len(prs), "file_inventory_complete": not errors,
            "prs": items}


def protection(api):
    branch = api.get("/branches/main")
    if not branch.get("protected"):
        return False, "main is unprotected", (), branch
    try:
        detail = api.get("/branches/main/protection")
    except ApiError as exc:
        # A ruleset or inaccessible protection is never assumed safe.
        return False, "Cannot independently read strict protection: " + str(exc), (), branch
    valid, reason = protection_is_enforced(branch, detail)
    checks = detail.get("required_status_checks") or {}
    contexts = set(checks.get("contexts") or ())
    contexts |= {x.get("context") for x in checks.get("checks") or () if x.get("context")}
    return valid, reason, sorted(contexts), branch


def evidence_for(api, item, required, old_main):
    number = item["number"]
    pr = api.get(f"/pulls/{number}")
    head = item["head_sha"]
    if pr.get("draft") or pr.get("state") != "open":
        return "DRAFT", "PR not ready or already closed"
    if pr["head"]["sha"] != head or pr["base"]["ref"] != "main":
        return "STALE_PR", "PR SHA/base changed after inventory"
    if pr["base"]["sha"] != old_main:
        return "STALE_MAIN", "PR has different canonical base HEAD"
    if pr.get("mergeable") is not True or pr.get("mergeable_state") != "clean":
        return "MERGE_CONFLICT", f"GitHub mergeable_state={pr.get('mergeable_state')}"
    commit = api.get(f"/commits/{head}")
    if skip_message(commit.get("commit", {}).get("message", "")):
        return "BLOCKED_SKIP_CI", "Final PR tip has GitHub CI skip directive"
    checks = api.pages(f"/commits/{head}/check-runs")
    if any(c.get("head_sha") != head for c in checks):
        return "UNVERIFIED", "Check run SHA does not match PR head"
    ok, reason = checks_pass(checks, required)
    if not ok:
        return "WAITING_CHECKS", reason
    # A conservative proof that the head is up-to-date before strict-protection merge.
    compare = api.get(f"/compare/main...{head}")
    if compare.get("behind_by") != 0:
        return "STALE_BASE", "PR head behind main; must rerun CI on rebased PR"
    reviews = api.pages(f"/pulls/{number}/reviews")
    if not latest_approval(reviews, head):
        return "HUMAN_REVIEW", "Missing exact-head APPROVED independent PR review"
    return "VERIFIED_READY", "Exact-head tests, review, branch and conflict gates passed"


def decide(api, report, apply, max_merges):
    eligible, reason, required, branch = protection(api)
    report["protection_gate"] = {"allow_merge": eligible, "reason": reason,
                                 "required_checks": list(required)}
    report["mode"] = "APPLY" if apply else "AUDIT"
    report["merge_events"] = []
    if not eligible:
        for item in report["prs"]:
            if item["status"] == "CANDIDATE":
                item["status"], item["reason"] = "BLOCKED_PROTECTION", reason
        return report
    # All network checks must use the freshly verified main SHA.
    base = branch["commit"]["sha"]
    if report["main_sha"] != base:
        raise ApiError("RACE", "main moved since inventory")
    for item in report["prs"]:
        if item["status"] != "CANDIDATE":
            continue
        status, rationale = evidence_for(api, item, required, base)
        item["status"], item["reason"] = status, rationale
        if status != "VERIFIED_READY" or not apply:
            continue
        if len(report["merge_events"]) >= max_merges:
            item["status"], item["reason"] = "QUEUED", "bounded per-run merge budget exhausted"
            continue
        current = api.get("/branches/main")["commit"]["sha"]
        fresh = api.get(f"/pulls/{item['number']}")
        if current != base or fresh["head"]["sha"] != item["head_sha"]:
            item["status"], item["reason"] = "RACE_ABORT", "HEAD changed before merge"
            break
        # Token is intentionally unable to override strict branch protection.
        response = api.put(f"/pulls/{item['number']}/merge",
                           {"sha": item["head_sha"], "merge_method": "squash",
                            "commit_title": f"Integrate reviewed PR #{item['number']}: {item['title'][:65]}",
                            "commit_message": "Verified exact-SHA integration through Smart Merge Coordinator."})
        if not response.get("merged") or not response.get("sha"):
            raise ApiError("MERGE", "GitHub did not confirm merge")
        item["status"], item["reason"] = "MERGED", "GitHub confirmed squash merge"
        report["merge_events"].append({"pr": item["number"], "before": base,
                                       "after": response["sha"], "head_sha": item["head_sha"]})
        # STOP after one changing merge. Remaining candidates must be reinventoried
        # against the new main; never reuse the previous conflict graph/checks.
        break
    return report


def persist_ledger(api, report):
    """Update exactly one existing GitHub issue; repeated identical runs are no-ops."""
    counts = dict(sorted(Counter(x["status"] for x in report["prs"]).items()))
    failures = [f"#{x['number']} {x['status']}: {x['reason']}"
                for x in report["prs"] if x["status"] not in ("CANDIDATE", "VERIFIED_READY")]
    digest = hashlib.sha256(json.dumps(
        {"main": report["main_sha"], "statuses": [(x["number"], x["head_sha"], x["status"], x["reason"])
         for x in report["prs"]]}, sort_keys=True).encode()).hexdigest()
    body = (f"<!-- smart-merge-ledger:{digest} -->\n"
            f"Canonical main: \`{report['main_sha']}\`\n\n"
            f"Protected: \`{report['main_protected']}\` — {report['protection_gate']['reason']}\n\n"
            f"PRs: {report['open_pr_count']} | Inventory complete: {report['file_inventory_complete']}\n\n"
            f"Status totals: \`{json.dumps(counts, sort_keys=True)}\`\n\n"
            "### Blocked PRs / next repair\n" + "\n".join("- " + x for x in failures[:200]) +
            "\n\nFull SHA-bound machine-readable JSON is attached to this workflow run.\n")
    issues = api.pages("/issues?state=open")
    found = [issue for issue in issues if issue["title"] == LEDGER_TITLE]
    if len(found) > 1:
        raise ApiError("LEDGER", "multiple control issues; refusing ambiguous write")
    if found:
        number = found[0]["number"]
        if found[0].get("body", "").startswith(f"<!-- smart-merge-ledger:{digest} -->"):
            return number
        api.patch(f"/issues/{number}", {"body": body})
        return number
    created = api.post("/issues", {"title": LEDGER_TITLE, "body": body})
    return created["number"]


def publish_summary(report, path):
    counts = dict(sorted(Counter(x["status"] for x in report["prs"]).items()))
    report["counts"] = counts
    text = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    Path(path).write_text(text, encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Public Smart Merge — exact main inventory\n\n")
            f.write(f"main: \`{report['main_sha']}\` | PRs: **{report['open_pr_count']}** "
                    f"| mode: **{report['mode']}**\n\n")
            f.write(f"Protection gate: **{report['protection_gate']['reason']}**\n\n")
            for k, v in counts.items():
                f.write(f"- {k}: {v}\n")
            f.write("\nNo release or content publication is performed.\n")
    print(json.dumps({"main_sha": report["main_sha"], "counts": counts,
                      "protection": report["protection_gate"],
                      "merged": report["merge_events"]}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "apply"), default="audit")
    parser.add_argument("--output", default="smart-merge-ledger.json")
    parser.add_argument("--publish-ledger", action="store_true")
    args = parser.parse_args()
    api = GitHub(os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPOSITORY", REPO))
    initial = inventory(api)
    # Fail closed on incomplete file graphs, including in audit mode.
    if not initial["file_inventory_complete"]:
        initial["protection_gate"] = {"allow_merge": False, "reason": "Incomplete file inventory",
                                      "required_checks": []}
        initial["mode"] = "AUDIT"
        initial["merge_events"] = []
    else:
        initial = decide(api, initial, args.mode == "apply", MAX_MERGES)
    publish_summary(initial, args.output)
    if args.publish_ledger:
        number = persist_ledger(api, initial)
        print(f"Ledger issue: https://github.com/{REPO}/issues/{number}")
    if initial.get("merge_events"):
        print("Main changed: next controller run must recompute the entire dependency graph.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
