#!/usr/bin/env python3
"""Run only affected public PR regression suites on the actual merge tree.

The gate supplies the checked-out synthetic PR merge commit (HEAD). Do not
consume user-supplied commands or test paths; every suite is hard-coded.
Missing Git metadata, tools or failing tests must fail the required CI gate.
"""
import shutil
import subprocess
import sys


SUITES = {
    "media": ("tools/media_optimizer", "test_compiler.py"),
    "pronunciation": ("tools/pronunciation_metadata", "test_metadata.py"),
    "audio": ("tools/audio_pronunciation", "test_admission.py"),
    "ingestion": ("tools/ingestion_circuit_breaker", "test_gate.py"),
    "final_evidence": ("tools/final_release_evidence", "test_compiler.py"),
    "corpus_dedupe": ("tools/corpus_dedupe", "test_dedupe.py"),
    "provenance_release": ("tools/provenance_release", "test_compiler.py"),
    "lexicon_sanitizer": ("tools/lexicon_sanitizer", "test_engine.py"),
    "artifact_digest": ("tools/artifact_digest", "test_engine.py"),
    "open_index": ("tools/open_index", "test_builder.py"),
    "repro_build": ("tools/repro_build", "test_compiler.py"),
    "pack_manifest": ("tools/pack_manifest", "test_builder.py"),
    "lexical_quality": ("tools/lexical_quality", "test_validator.py"),
    "open_export": ("tools/open_export", "test_lifecycle.py"),
    "community_automation": ("tools/community_automation", "test_gate.py"),
    "registry_unit": ("catalog", "test_registry.py"),
    "utils": ("tests", "test_utils.py"),
}
ORDER = ("media", "pronunciation", "audio", "ingestion", "final_evidence", "corpus_dedupe", "provenance_release", "lexicon_sanitizer", "artifact_digest", "open_index", "repro_build", "pack_manifest", "lexical_quality", "open_export", "community_automation", "utils", "registry_unit")


# Only independently tested leaf components may bypass *unrelated* global
# fixtures. Unknown, central, license, language, and pack changes fail closed.
BASELINE_ORDER = ("policy", "registry", "sqlite")
BASELINE_COMMANDS = {
    "policy": (sys.executable, "-m", "unittest", "discover",
               "-s", "tests/ci_policy", "-p", "test_*.py", "-v"),
    "registry": (sys.executable, "catalog/validate_registry.py"),
    "sqlite": (sys.executable, "tools/test_store_pipeline.py", "-q"),
}
ISOLATED_PREFIXES = tuple(folder + "/" for folder, _ in SUITES.values() if folder not in ("tests", "catalog"))
POLICY_PATHS = ("tools/ci_policy/", "tests/ci_policy/")
POLICY_WORKFLOW = ".github/workflows/public_pr_merge_gate.yml"
SENSITIVE_DOCS = ("docs/governance/", "docs/merge_coordinator/",
                  "docs/security/", "docs/release/", "docs/CI_")


def select_baseline_checks(changed_paths):
    """Choose cost-effective global checks; never skip unknown or shared changes."""
    if not changed_paths:
        return BASELINE_ORDER
    for path in changed_paths:
        if (not isinstance(path, str) or not path or "\\" in path
                or path.startswith("/") or ".." in path.split("/")):
            return BASELINE_ORDER

    def low_risk(path):
        if any(path.startswith(prefix) for prefix in ISOLATED_PREFIXES):
            return True
        if path.startswith("docs/") and path.endswith(".md"):
            return not path.startswith(SENSITIVE_DOCS)
        return path.startswith(POLICY_PATHS) or path == POLICY_WORKFLOW

    if not all(low_risk(path) for path in changed_paths):
        return BASELINE_ORDER
    if any(path.startswith(POLICY_PATHS) or path == POLICY_WORKFLOW
           for path in changed_paths):
        return ("policy",)
    return ()


def execute_baseline_checks(selected):
    """A selected global check is mandatory: errors/timeouts propagate."""
    for name in selected:
        command = BASELINE_COMMANDS[name]
        print("BASELINE_CHECK_RUNNING=" + name, flush=True)
        subprocess.run(command, check=True, timeout=240)
        print("BASELINE_CHECK_PASSED=" + name, flush=True)


def select_suites(changed_paths):
    selected = set()
    for path in changed_paths:
        if not isinstance(path, str) or not path or "\\" in path or ".." in path.split("/"):
            continue
        if path.startswith("tools/media_optimizer/"):
            selected.add("media")
        if path.startswith("tools/pronunciation_metadata/"):
            selected.add("pronunciation")
        if path.startswith("tools/audio_pronunciation/"):
            selected.add("audio")
        if path.startswith("tools/ingestion_circuit_breaker/"):
            selected.add("ingestion")
        if path.startswith("tools/final_release_evidence/"):
            selected.add("final_evidence")
        if path.startswith("tools/corpus_dedupe/"):
            selected.add("corpus_dedupe")
        if path.startswith("tools/provenance_release/"):
            selected.add("provenance_release")
        if path.startswith("tools/lexicon_sanitizer/"):
            selected.add("lexicon_sanitizer")
        if path.startswith("tools/artifact_digest/"):
            selected.add("artifact_digest")
        if path.startswith("tools/open_index/"):
            selected.add("open_index")
        if path.startswith("tools/repro_build/"):
            selected.add("repro_build")
        if path.startswith("tools/pack_manifest/"):
            selected.add("pack_manifest")
        if path.startswith("tools/lexical_quality/"):
            selected.add("lexical_quality")
        if path.startswith("tools/open_export/"):
            selected.add("open_export")
        if path.startswith("tools/community_automation/"):
            selected.add("community_automation")
        if path == "utils.py" or path == "tests/test_utils.py":
            selected.add("utils")
        if path.startswith("catalog/"):
            selected.add("registry_unit")
        if path.startswith("legal/ledger/"):
            selected.update(name for name in ORDER if name != "utils")
        if path.startswith("tools/contribution_gate/"):
            selected.update(("pronunciation", "audio"))
    return tuple(name for name in ORDER if name in selected)


def changed_in_synthetic_merge():
    # --no-renames includes both sides of a rename and preserves deletion paths.
    result = subprocess.run(
        ("git", "diff", "--no-renames", "--name-only", "-z", "HEAD^1", "HEAD"),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=20,
    )
    return [name.decode("utf-8", errors="strict") for name in result.stdout.split(b"\0") if name]


def execute_suites(selected):
    if "audio" in selected and shutil.which("ffmpeg") is None:
        raise RuntimeError("audio QA cannot run: ffmpeg is unavailable")
    for name in selected:
        folder, pattern = SUITES[name]
        print("SCOPED_TEST_RUNNING=" + name, flush=True)
        subprocess.run(
            (sys.executable, "-m", "unittest", "discover", "-s", folder, "-p", pattern, "-v"),
            check=True, timeout=240,
        )
        print("SCOPED_TEST_PASSED=" + name, flush=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in ([], ["--baseline"]):
        raise SystemExit("usage: run_scoped_pr_tests.py [--baseline]")
    changed_paths = changed_in_synthetic_merge()
    if argv == ["--baseline"]:
        selected = select_baseline_checks(changed_paths)
        print("BASELINE_CHECK_SELECTION=" +
              (",".join(selected) if selected else "none"), flush=True)
        execute_baseline_checks(selected)
    else:
        selected = select_suites(changed_paths)
        print("SCOPED_TEST_SELECTION=" +
              (",".join(selected) if selected else "none"), flush=True)
        execute_suites(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
