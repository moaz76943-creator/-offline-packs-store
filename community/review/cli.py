#!/usr/bin/env python3
"""Operator-only, fail-closed review CLI. Decisions must be pre-signed externally."""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

from community.review.state_machine import ReviewStateMachine


def read_operator_keys(path, prohibited_roots):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise PermissionError("operator key file must be regular and mode 0600")
    for root in prohibited_roots:
        if path.resolve().is_relative_to(Path(root).resolve()):
            raise PermissionError("operator key file must be outside corpus and repository")
    if path.stat().st_size > 16384:
        raise ValueError("oversized key file")
    doc = json.loads(path.read_text(encoding="utf-8"))
    validators = {k: base64.b64decode(v, validate=True) for k, v in doc["validators"].items()}
    reviewers = {k: base64.b64decode(v, validate=True) for k, v in doc["reviewers"].items()}
    return validators, reviewers


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--operator-keys", required=True, type=Path)
    parser.add_argument("action", choices=("submit", "start", "validate", "approve", "reject", "eligible", "enqueue"))
    parser.add_argument("--id")
    parser.add_argument("--sha256")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--actor")
    parser.add_argument("--token")
    args = parser.parse_args(argv)

    if args.action != "enqueue" and not args.id:
        parser.error("--id is required")

    try:
        root = Path(__file__).resolve().parents[2]
        validators, reviewers = read_operator_keys(args.operator_keys, (root, args.storage, args.artifacts))
        machine = ReviewStateMachine(args.storage, args.artifacts,
                                     validator_keys=validators, reviewer_keys=reviewers)
        if args.action == "submit":
            if args.metadata is None or args.sha256 is None or args.artifact is None:
                raise ValueError("submission requires --metadata, --sha256 and --artifact")
            if args.metadata.is_symlink() or args.metadata.stat().st_size > 16384:
                raise ValueError("unsafe metadata file")
            meta = json.loads(args.metadata.read_text(encoding="utf-8"))
            outcome = machine.submit(args.id, args.sha256, meta, args.artifact)
        elif args.action == "start":
            outcome = machine.start_validation(args.id)
        elif args.action == "validate":
            outcome = machine.complete_validation(args.id, args.actor, args.token)
        elif args.action in ("approve", "reject"):
            outcome = machine.review(args.id, args.actor, args.action == "approve", args.token)
        elif args.action == "enqueue":
            if not args.artifact:
                raise ValueError("enqueue requires --artifact")
            machine.enqueue_manifest(args.artifact)
            outcome = {"enqueued": True}
        else:
            outcome = machine.mark_published_eligible(args.id)
        # Never print authority keys, HMAC tokens or unredacted contributor metadata.
        if args.action == "enqueue":
            print(json.dumps(outcome, sort_keys=True))
        else:
            print(json.dumps({k: outcome[k] for k in ("submission_id", "content_hash", "revision", "state")}, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, PermissionError, TypeError) as error:
        print("BLOCKED:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
