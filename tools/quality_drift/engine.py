"""Offline immutable quality-baseline records and conservative regression comparisons.

A SHA-pinned GitHub URL is not a verified run or release approval. This tool
never performs network requests, creates production packs, or exports learner data.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlparse

STATUSES = frozenset(("PASS", "FAIL", "NOT_RUN", "UNKNOWN", "STALE"))
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
PRIVATE_FIELDS = frozenset(("learner_id", "user_id", "device_id", "email",
                            "phone", "srs_history", "review_history",
                            "lesson_history", "access_token", "token", "secret",
                            "raw_text", "name", "translations", "words",
                            "examples", "learner_data"))
MAX_DOC = 1024 * 1024
MAX_METRICS = 100


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canon(value)).hexdigest()


def is_github_commit_evidence(url, repo, sha):
    if not isinstance(url, str) or len(url) > 1024:
        return False
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "github.com" or
                parsed.username or parsed.password or parsed.port or
                parsed.query or parsed.fragment):
            return False
        return bool(re.fullmatch(re.escape("/" + repo + "/") +
                                 r"(?:commit|blob|tree)/" + re.escape(sha) +
                                 r"(?:/[^?#]*)?", parsed.path))
    except ValueError:
        return False


def has_sensitive_data(obj, depth=0):
    if depth > 7:
        return True
    if isinstance(obj, dict):
        return any(str(k).casefold() in PRIVATE_FIELDS or has_sensitive_data(v, depth + 1)
                   for k, v in obj.items())
    if isinstance(obj, list):
        return len(obj) > 200 or any(has_sensitive_data(v, depth + 1) for v in obj)
    return False


def _valid_nonnegative(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def validate_thresholds(thresholds):
    if not isinstance(thresholds, dict) or thresholds.get("schema_version") != "1.0.0":
        raise ValueError("unsupported thresholds")
    definitions = thresholds.get("metrics")
    if not isinstance(definitions, dict) or not definitions or len(definitions) > MAX_METRICS:
        raise ValueError("invalid threshold metrics")
    for name, spec in definitions.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", name):
            raise ValueError("invalid metric name")
        if not isinstance(spec, dict) or spec.get("direction") not in ("higher", "lower") or spec.get("unit") not in ("count", "bytes", "ms", "percent"):
            raise ValueError("invalid metric spec")
        for key, value in spec.items():
            if key in ("direction", "unit"):
                continue
            if key not in ("absolute_drop", "absolute_increase", "relative_drop_pct", "relative_increase_pct") or not _valid_nonnegative(value) or (key.endswith("_pct") and value > 100):
                raise ValueError("invalid threshold")
    return definitions


def validate_baseline(data, definitions, *, expected_head=None, allow_fixture=False):
    if not isinstance(data, dict) or data.get("schema_version") != "1.0.0":
        raise ValueError("invalid baseline schema")
    if has_sensitive_data(data):
        raise ValueError("possible private data")
    if not isinstance(data.get("version"), str) or not VERSION.fullmatch(data["version"]):
        raise ValueError("invalid version")
    repo, branch, sha = data.get("repository"), data.get("branch"), data.get("head_sha")
    if (not isinstance(repo, str) or not REPO.fullmatch(repo) or
            not isinstance(branch, str) or not branch or len(branch) > 128 or
            not isinstance(sha, str) or not SHA.fullmatch(sha)):
        raise ValueError("invalid anchor")
    if expected_head is not None and sha != expected_head:
        raise ValueError("HEAD_SHA_MISMATCH")
    if data.get("data_class") not in ("production", "fixture"):
        raise ValueError("invalid data class")
    if data["data_class"] == "fixture" and not allow_fixture:
        raise ValueError("fixture not allowed as production")
    prior = data.get("previous_digest")
    if prior is not None and (not isinstance(prior, str) or not DIGEST.fullmatch(prior)):
        raise ValueError("invalid previous digest")
    approval = data.get("approval")
    if not isinstance(approval, dict) or approval.get("status") not in ("APPROVED", "PENDING", "REJECTED"):
        raise ValueError("invalid approval")
    if data["data_class"] == "fixture" and approval["status"] == "APPROVED":
        raise ValueError("fixture cannot be approved")
    if approval["status"] == "APPROVED" and not is_github_commit_evidence(approval.get("evidence_url"), repo, sha):
        raise ValueError("approval not SHA pinned")
    sources = data.get("source_refs")
    if not isinstance(sources, dict) or sources.get("public") != {"repository": repo, "branch": branch, "head_sha": sha}:
        raise ValueError("source anchor mismatch")
    for label, source in sources.items():
        if (not isinstance(label, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", label)
                or not isinstance(source, dict)):
            raise ValueError("invalid source")
        if (not isinstance(source.get("repository"), str) or
                not REPO.fullmatch(source["repository"]) or
                not isinstance(source.get("head_sha"), str) or
                not SHA.fullmatch(source["head_sha"]) or
                not isinstance(source.get("branch"), str) or not source["branch"]):
            raise ValueError("invalid source SHA")
        if label != "public" and source.get("sanitized_export") is not True:
            raise ValueError("external evidence not sanitized")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or len(metrics) > MAX_METRICS:
        raise ValueError("invalid metrics")
    for name, evidence in metrics.items():
        if name not in definitions or not isinstance(evidence, dict):
            raise ValueError("unrecognized metric")
        status, value, source = evidence.get("status"), evidence.get("value"), evidence.get("source")
        if status not in STATUSES or source not in sources:
            raise ValueError("invalid metric status")
        if status in ("PASS", "FAIL"):
            if not _valid_nonnegative(value):
                raise ValueError("invalid measured value")
            if definitions[name]["unit"] == "count" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError("count must be integer")
            if definitions[name]["unit"] == "percent" and value > 100:
                raise ValueError("invalid percentage")
            method = evidence.get("measurement_method")
            if not isinstance(method, str) or not method.strip() or len(method) > 120:
                raise ValueError("missing measurement method")
            anchor = sources[source]
            if not is_github_commit_evidence(evidence.get("evidence_url"), anchor["repository"], anchor["head_sha"]):
                raise ValueError("metric not SHA-pinned")
            if evidence.get("evidence_sha") != anchor["head_sha"]:
                raise ValueError("EVIDENCE_SHA_MISMATCH")
            if evidence.get("test_fixture") is True and data["data_class"] == "production":
                raise ValueError("fixture metric in production")
        elif value is not None:
            raise ValueError("unknown/not-run/stale cannot be zero")
    if len(canon(data)) > MAX_DOC:
        raise ValueError("oversized record")
    return data


def persist_immutable(baseline, definitions, directory, *, expected_head=None, allow_fixture=False):
    validate_baseline(baseline, definitions, expected_head=expected_head, allow_fixture=allow_fixture)
    root = Path(directory)
    if root.is_symlink():
        raise ValueError("unsafe output directory")
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = digest(baseline)
    payload = canon({"baseline": baseline, "digest_sha256": fingerprint}) + b"\n"
    target = root / (baseline["version"] + ".json")
    if target.exists() or target.is_symlink():
        present = load_baseline(target, definitions, allow_fixture=allow_fixture)
        if digest(present) != fingerprint:
            raise FileExistsError("version already recorded differently")
        return target, fingerprint
    fd, temp = tempfile.mkstemp(prefix=".pending-", suffix=".json", dir=root)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temp, target, follow_symlinks=False)
    finally:
        os.unlink(temp)
    return target, fingerprint


def load_baseline(path, definitions, *, allow_fixture=False):
    source = Path(path)
    if source.is_symlink() or source.stat().st_size > MAX_DOC + 1024:
        raise ValueError("unsafe baseline")
    wrapped = json.loads(source.read_text(encoding="utf-8"))
    if (not isinstance(wrapped, dict) or set(wrapped) != {"baseline", "digest_sha256"}
            or wrapped["digest_sha256"] != digest(wrapped["baseline"])):
        raise ValueError("baseline integrity mismatch")
    base = validate_baseline(wrapped["baseline"], definitions, allow_fixture=allow_fixture)
    if source.name != base["version"] + ".json":
        raise ValueError("version filename mismatch")
    return base


def compare(previous, current, definitions):
    report = {"schema_version": "1.0.0", "previous_version": previous.get("version"),
              "current_version": current.get("version"), "overall": "UNKNOWN",
              "publication_approved": False, "quality_score_10": None,
              "changes": {}, "alerts": [], "notes": [],
              "evidence_validation": "SHA_PINNED_NOT_GITHUB_AUTHENTICATED"}
    if previous.get("approval", {}).get("status") != "APPROVED":
        report["notes"].append("PREVIOUS_BASELINE_NOT_APPROVED")
        return report
    if previous.get("data_class") != "production" or current.get("data_class") != "production":
        report["notes"].append("FIXTURE_OR_NON_PRODUCTION_BASELINE")
        return report
    if current.get("previous_digest") != digest(previous):
        report["overall"] = "STALE"
        report["notes"].append("PREVIOUS_DIGEST_MISMATCH")
        return report
    if previous.get("repository") != current.get("repository") or previous.get("branch") != current.get("branch"):
        report["overall"] = "STALE"
        report["notes"].append("BRANCH_OR_REPOSITORY_MISMATCH")
        return report
    outcomes = []
    for name, spec in definitions.items():
        before = previous["metrics"].get(name, {"status": "UNKNOWN", "value": None})
        after = current["metrics"].get(name, {"status": "UNKNOWN", "value": None})
        entry = {"previous_status": before["status"], "current_status": after["status"],
                 "previous": None, "current": None, "delta": None,
                 "status": "UNKNOWN", "evidence_urls": []}
        for metric in (before, after):
            url = metric.get("evidence_url")
            if isinstance(url, str) and url.startswith("https://github.com/"):
                entry["evidence_urls"].append(url)
        if "STALE" in (before["status"], after["status"]):
            entry["status"] = "STALE"
        elif "NOT_RUN" in (before["status"], after["status"]):
            entry["status"] = "NOT_RUN"
        elif "UNKNOWN" in (before["status"], after["status"]):
            entry["status"] = "UNKNOWN"
        elif after["status"] == "FAIL":
            entry.update({"status": "FAIL", "previous": before["value"],
                          "current": after["value"]})
        else:
            old, new = before["value"], after["value"]
            delta = new - old
            entry.update({"status": "PASS", "previous": old,
                          "current": new, "delta": delta})
            if spec["direction"] == "higher":
                regression = ((old - new) > spec.get("absolute_drop", float("inf")) or
                              (old > 0 and ((old - new) / old * 100) > spec.get("relative_drop_pct", float("inf"))))
            else:
                regression = ((new - old) > spec.get("absolute_increase", float("inf")) or
                              (old > 0 and ((new - old) / old * 100) > spec.get("relative_increase_pct", float("inf"))))
                if old == 0 and new > 0 and "relative_increase_pct" in spec:
                    regression = True
            if regression:
                entry["status"] = "FAIL"
        report["changes"][name] = entry
        outcomes.append(entry["status"])
        if entry["status"] == "FAIL":
            report["alerts"].append({"metric": name,
                                     "reason": "CRITICAL_REGRESSION_OR_FAILED_GATE",
                                     "evidence_urls": entry["evidence_urls"]})
    for severity in ("FAIL", "STALE", "NOT_RUN", "UNKNOWN"):
        if severity in outcomes:
            report["overall"] = severity
            break
    else:
        if outcomes:
            report["overall"] = "PASS"
    return report


def render_markdown(report):
    labels = {"PASS": "ناجح", "FAIL": "تدهور/فشل", "STALE": "دليل قديم",
              "UNKNOWN": "مجهول", "NOT_RUN": "لم ينفذ"}
    lines = ["# تقرير تغير الجودة — DEUTSCH", "",
             "**هذا التقرير لا يمنح موافقة دمج أو نشر أو درجة 10/10.**", "",
             "- الإصدار السابق: " + str(report.get("previous_version")),
             "- الإصدار الجاري: " + str(report.get("current_version")),
             "- النتيجة: " + labels.get(report["overall"], report["overall"]), "",
             "| المقياس | النتيجة | السابق | الحالي | الفرق |",
             "|---|---|---:|---:|---:|"]
    for key, e in report["changes"].items():
        def fmt(v):
            return "—" if v is None else str(v)
        lines.append("| " + " | ".join([key, labels.get(e["status"], e["status"]),
                                         fmt(e["previous"]), fmt(e["current"]), fmt(e["delta"])]) + " |")
    lines += ["", "## الأدلة والتوصيات"]
    for alert in report["alerts"]:
        lines.append("- " + alert["metric"] + ": راجع أدلة GitHub قبل الإصلاح. " +
                     ", ".join(alert["evidence_urls"]))
    for note in report["notes"]:
        lines.append("- تنبيه: " + note)
    lines += ["", "SHA-pinned URLs are claims; this offline tool does not authenticate CI or GitHub."]
    return "\n".join(lines)


def load_json(path):
    source = Path(path)
    if source.is_symlink() or source.stat().st_size > MAX_DOC:
        raise ValueError("unsafe input")
    return json.loads(source.read_text(encoding="utf-8"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--thresholds", default=str(Path(__file__).with_name("thresholds.json")))
    sub = p.add_subparsers(dest="mode", required=True)
    write = sub.add_parser("record")
    write.add_argument("--input", required=True)
    write.add_argument("--directory", required=True)
    write.add_argument("--expected-head", required=True)
    write.add_argument("--allow-fixture", action="store_true")
    check = sub.add_parser("compare")
    check.add_argument("--previous", required=True)
    check.add_argument("--current", required=True)
    check.add_argument("--format", choices=["json", "markdown"], default="json")
    check.add_argument("--allow-fixture", action="store_true")
    args = p.parse_args(argv)
    try:
        definitions = validate_thresholds(load_json(args.thresholds))
        if args.mode == "record":
            target, fingerprint = persist_immutable(load_json(args.input), definitions, args.directory,
                                                    expected_head=args.expected_head,
                                                    allow_fixture=args.allow_fixture)
            print(json.dumps({"stored_version": target.name, "sha256": fingerprint,
                              "publication_approved": False}))
        else:
            old = load_baseline(args.previous, definitions, allow_fixture=args.allow_fixture)
            new = load_baseline(args.current, definitions, allow_fixture=args.allow_fixture)
            result = compare(old, new, definitions)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True) if args.format == "json" else render_markdown(result))
        return 0
    except (OSError, TypeError, ValueError, KeyError, FileExistsError):
        print(json.dumps({"status": "UNKNOWN", "error": "INVALID_OR_UNVERIFIED_EVIDENCE",
                          "publication_approved": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
