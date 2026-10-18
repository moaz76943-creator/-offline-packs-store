"""Offline CLI: python3 -m tools.proficiency_mapping validate | map ..."""
import argparse
import json
from .engine import ProficiencyCatalog, read_json, validate_curricula


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence-aware, offline proficiency API")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("validate", help="Validate bundled definitions, mappings and pilot fixtures")
    map_parser = subs.add_parser("map", help="Query an explicitly documented comparison")
    map_parser.add_argument("from_framework")
    map_parser.add_argument("from_level")
    map_parser.add_argument("to_framework")
    map_parser.add_argument("--passed", action="store_true")
    map_parser.add_argument("--score", type=int)
    map_parser.add_argument("--skill", choices=("reading", "writing", "listening", "speaking"))
    args = parser.parse_args()
    catalog = ProficiencyCatalog()
    if args.command == "validate":
        fixtures = read_json("pilot_fixtures.json")
        if fixtures.get("schema_version") != "1.0.0":
            raise ValueError("Invalid fixture version")
        catalog.validate_records(fixtures["records"])
        validate_curricula(read_json("curricula.json"), catalog)
        print(json.dumps({"valid": True, "pilot_records": len(fixtures["records"])}, sort_keys=True))
    else:
        print(json.dumps(catalog.map_level(args.from_framework, args.from_level, args.to_framework,
                                           passed=args.passed, total_score=args.score, skill=args.skill), sort_keys=True))


if __name__ == "__main__":
    main()
