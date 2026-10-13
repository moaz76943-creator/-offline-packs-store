"""Fail-closed verification that PR checks run against the expected, unskipped tip.

A branch-protection-required `pull_request` check is skipped by GitHub if the PR
HEAD commit contains a skip directive. This small guard also authenticates the
second parent of the synthetic PR merge checkout, so tests cover the exact PR.
"""

import argparse
import re
import subprocess

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\\Z")
SKIP_TOKEN = re.compile(r"\\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\\]", re.IGNORECASE)
SKIP_TRAILER = re.compile(r"(?im)^skip-checks\\s*:\\s*true\\s*$")


def skip_directive(message: str):
    """Return offending skip instruction, or None if PR checks may run."""
    match = SKIP_TOKEN.search(message) or SKIP_TRAILER.search(message)
    return match.group(0) if match else None


def git_output(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True, stderr=subprocess.PIPE)


def verify_pr_checkout(expected_head_sha: str) -> str:
    """Verify the GitHub PR merge checkout's second parent and final commit."""
    if not SHA.fullmatch(expected_head_sha):
        raise ValueError('invalid expected SHA')
    checked_head = git_output('rev-parse', '--verify', 'HEAD^2').strip()
    if checked_head != expected_head_sha:
        raise ValueError(f'wrong PR head: expected {expected_head_sha}, got {checked_head}')
    message = git_output('log', '-1', '--format=%B', expected_head_sha)
    directive = skip_directive(message)
    if directive:
        raise ValueError(f'PR tip contains skip directive {directive}; create a reviewed, non-skipping final commit')
    return expected_head_sha


def main() -> int:
    p = argparse.ArgumentParser(description='Check exact PR head and skip-token policy')
    p.add_argument('--expected-head', required=True)
    opts = p.parse_args()
    try:
        sha = verify_pr_checkout(opts.expected_head)
    except (ValueError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'FAIL CLOSED: {exc}\\n')
    print(f'PASS: verified PR merge checkout and unskipped head {sha}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
