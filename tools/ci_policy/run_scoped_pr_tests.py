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
}
ORDER = ("media", "pronunciation", "audio", "ingestion", "final_evidence", "corpus_dedupe", "provenance_release", "lexicon_sanitizer", "artifact_digest", "open_index")


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
        if path.startswith("legal/ledger/"):
            selected.update(ORDER)
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


def main():
    selected = select_suites(changed_in_synthetic_merge())
    print("SCOPED_TEST_SELECTION=" + (",".join(selected) if selected else "none"), flush=True)
    execute_suites(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
