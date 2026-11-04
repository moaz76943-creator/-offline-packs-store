"""CEFR evidence gate with protected input and staged outputs."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from tools.cefr_validation.validator import CEFRValidator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Executable evidence gate for lexical A1-C2 classifications."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--rejected", type=Path, required=True)
    return parser.parse_args()


def verify_paths(source, accepted, rejected):
    paths = (source, accepted, rejected)

    if len({p.expanduser().resolve() for p in paths}) != len(paths):
        raise ValueError("Input and output paths must be distinct")

    for i, first in enumerate(paths):
        for second in paths[i + 1:]:
            if first.exists() and second.exists():
                if os.path.samefile(first, second):
                    raise ValueError(
                        "Input and output paths must be distinct"
                    )

    if not source.is_file():
        raise ValueError("Input must be an existing file")

    for dest in (accepted, rejected):
        if dest.is_symlink() or dest.is_dir() or not dest.parent.is_dir():
            raise ValueError(
                "Output path must be a regular-file destination"
            )


def stream_records(source):
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def main():
    args = parse_args()

    verify_paths(
        args.input,
        args.accepted,
        args.rejected
    )

    validator = CEFRValidator()
    pending = []

    try:
        for target in (args.accepted, args.rejected):
            f = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".tmp"
            )
            pending.append((Path(f.name), f, target))

        accepted = pending[0][1]
        rejected = pending[1][1]

        for status, record, reason in validator.validate_stream(
            stream_records(args.input)
        ):
            if status == "accepted":
                accepted.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )
            else:
                rejected.write(
                    json.dumps(
                        {"record": record, "reason": reason},
                        ensure_ascii=False
                    ) + "\n"
                )

        for _, f, _ in pending:
            f.flush()
            os.fsync(f.fileno())
            f.close()

        # Replace outputs only after full validation.
        for temp, _, target in pending:
            os.replace(temp, target)

    finally:
        for temp, f, _ in pending:
            if not f.closed:
                f.close()
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
