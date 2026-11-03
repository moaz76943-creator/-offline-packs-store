"""Authenticate the exact PR head in GitHub's synthetic merge checkout.

CI-skip markers in commit messages are not policy violations. GitHub may avoid
scheduling a pull_request workflow when the tip carries such a marker; absent
hosted checks still cannot satisfy required branch protection. This function
only checks that a running job is testing the intended PR head.
"""

import argparse
import re
import subprocess

SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
def git_output(*args: str) -> str:
    return subprocess.check_output(['git', *args], text=True, stderr=subprocess.PIPE)


def verify_pr_checkout(expected_head_sha: str) -> str:
    """Verify the GitHub PR merge checkout's second parent."""
    if not SHA.fullmatch(expected_head_sha):
        raise ValueError('invalid expected SHA')
    checked_head = git_output('rev-parse', '--verify', 'HEAD^2').strip()
    if checked_head != expected_head_sha:
        raise ValueError(f'wrong PR head: expected {expected_head_sha}, got {checked_head}')
    return expected_head_sha


def main() -> int:
    p = argparse.ArgumentParser(description='Authenticate exact PR head')
    p.add_argument('--expected-head', required=True)
    opts = p.parse_args()
    try:
        sha = verify_pr_checkout(opts.expected_head)
    except (ValueError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'FAIL CLOSED: {exc}\n')
    print(f'PASS: verified exact PR merge checkout head {sha}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
