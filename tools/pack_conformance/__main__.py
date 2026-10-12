import argparse
import sys
import pathlib

from .engine import verify_pack, ConformanceError, UnverifiedWarning

def main():
    parser = argparse.ArgumentParser(description="Pack Conformance Tester")
    parser.add_argument("pack_file", type=pathlib.Path, help="Path to the .pack.gz file to verify")

    args = parser.parse_args()

    try:
        verify_pack(args.pack_file)
        print(f"PASS: {args.pack_file} conforms to requirements.")
        sys.exit(0)
    except UnverifiedWarning as e:
        print(f"UNVERIFIED: {e}", file=sys.stderr)
        sys.exit(2)
    except ConformanceError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected exception: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
