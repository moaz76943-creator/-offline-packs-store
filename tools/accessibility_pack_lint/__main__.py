import argparse
import json
import sys
from .validator import AccessibilityValidator

def main():
    parser = argparse.ArgumentParser(description="Multilingual Semantic Asset Accessibility Validator")
    parser.add_argument("--input", type=str, required=True, help="Path to input JSON file containing array of assets")
    parser.add_argument("--changed-only", action="store_true", help="Only validate assets that have changed flag set to true")

    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"Failed to read input: {e}"}))
        sys.exit(1)

    if not isinstance(data, list):
        print(json.dumps({"error": "Input JSON must be a list of assets"}))
        sys.exit(1)

    validator = AccessibilityValidator()
    results = {}

    for idx, asset in enumerate(data):
        if args.changed_only and not asset.get("changed", False):
            continue

        asset_id = asset.get("id", f"unknown_{idx}")
        results[asset_id] = validator.validate_asset(asset)

    print(json.dumps(results, indent=2))

    # Optional exit code logic: if any asset rejected, exit non-zero
    if any(res["status"] == "rejected" for res in results.values()):
        sys.exit(1)

if __name__ == "__main__":
    main()
