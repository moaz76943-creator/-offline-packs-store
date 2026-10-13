"""Read-only, fail-closed GitHub CI run identity attestation.

The caller must fetch *fresh* PR, workflow run and job objects from GitHub.
This module neither contacts GitHub nor authorizes a release. A passing
attestation proves only that the supplied evidence is internally consistent.
"""
import json
import re
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = "moaz76943-creator/-offline-packs-store"


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def evaluate(pr: dict, run: dict, jobs: list, *, workflow_path: str,
             required_jobs: tuple[str, ...], event: str = "pull_request") -> dict:
    """Fail closed for stale/wrong SHA, workflow, repository, run or jobs.

    PR is expected to contain {number, state, head: {sha, repo:{full_name}}}.
    Run is a REST workflow-run object and jobs are from that exact run.
    A successful result is NOT a release decision and does not verify sources.
    """
    errors = []
    if not isinstance(pr, dict) or not isinstance(run, dict) or not isinstance(jobs, list):
        return {"status": "BLOCKED", "errors": ["INVALID_EVIDENCE_SHAPE"]}
    if not workflow_path.startswith(".github/workflows/") or not workflow_path.endswith((".yml", ".yaml")):
        errors.append("INVALID_WORKFLOW_POLICY")
    if not required_jobs or any(not isinstance(n, str) or not n for n in required_jobs) or len(set(required_jobs)) != len(required_jobs):
        errors.append("INVALID_JOB_POLICY")
    pr_head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    pr_repo = pr_head.get("repo") if isinstance(pr_head.get("repo"), dict) else {}
    if pr.get("state") != "open" or not _positive_int(pr.get("number")):
        errors.append("PR_NOT_OPEN")
    if pr_repo.get("full_name") != _REPO:
        errors.append("WRONG_PR_REPOSITORY")
    expected_sha = pr_head.get("sha")
    if not _sha(expected_sha):
        errors.append("INVALID_PR_SHA")
    if run.get("repository", {}).get("full_name") != _REPO if isinstance(run.get("repository"), dict) else True:
        errors.append("WRONG_RUN_REPOSITORY")
    if run.get("head_sha") != expected_sha or not _sha(run.get("head_sha")):
        errors.append("STALE_OR_WRONG_RUN_SHA")
    if run.get("event") != event:
        errors.append("WRONG_EVENT")
    if run.get("path") != workflow_path:
        errors.append("WRONG_WORKFLOW_PATH")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        errors.append("RUN_NOT_SUCCESSFUL")
    if not _positive_int(run.get("id")) or not _positive_int(run.get("run_attempt")):
        errors.append("INVALID_RUN_IDENTITY")
    if event == "pull_request":
        prs = run.get("pull_requests")
        if not isinstance(prs, list) or not any(isinstance(p, dict) and p.get("number") == pr.get("number") for p in prs):
            errors.append("RUN_NOT_BOUND_TO_PR")
    if not isinstance(jobs, list) or not jobs:
        errors.append("MISSING_JOBS")
    else:
        seen = set()
        for job in jobs:
            if not isinstance(job, dict):
                errors.append("INVALID_JOB"); continue
            name = job.get("name")
            if not isinstance(name, str) or name in seen:
                errors.append("DUPLICATE_OR_INVALID_JOB_NAME")
            else:
                seen.add(name)
            if job.get("run_id") != run.get("id") or not _positive_int(job.get("id")):
                errors.append("JOB_RUN_ID_MISMATCH")
            if job.get("status") != "completed" or job.get("conclusion") != "success":
                errors.append("JOB_NOT_SUCCESSFUL")
        for required in required_jobs:
            if required not in seen:
                errors.append("REQUIRED_JOB_MISSING")
    errors = sorted(set(errors))
    return {"status": "BLOCKED" if errors else "EVIDENCE_MATCH",
            "errors": errors, "pr_head_sha": expected_sha if _sha(expected_sha) else None,
            "run_id": run.get("id") if _positive_int(run.get("id")) else None,
            "run_attempt": run.get("run_attempt") if _positive_int(run.get("run_attempt")) else None,
            "publication_approved": False}


def main():
    """Accept a single local JSON evidence object on stdin; no network or writes."""
    import sys
    try:
        obj = json.load(sys.stdin)
        result = evaluate(obj["pr"], obj["run"], obj["jobs"],
                          workflow_path=obj["workflow_path"],
                          required_jobs=tuple(obj["required_jobs"]),
                          event=obj.get("event", "pull_request"))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        result = {"status": "BLOCKED", "errors": ["INVALID_INPUT"], "publication_approved": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "EVIDENCE_MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
