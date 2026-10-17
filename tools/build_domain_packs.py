import sys
import gzip
import json
import argparse
from pathlib import Path

# شجرة المجالات الدلالية المستهدفة
DOMAINS = {
    "kitchen": ["kitchen", "cooking", "food", "tableware", "utensil", "Küche", "Kochen"],
    "home": ["home", "house", "furniture", "room", "Wohnung", "Haus", "Möbel"],
    "family": ["family", "kinship", "relatives", "Familie", "Verwandtschaft"]
}

def parse_args():
    parser = argparse.ArgumentParser(description="Extract domain-specific dictionary packs.")
    parser.add_argument("--input", required=True, help="Path to input jsonl.gz")
    parser.add_argument("--out-dir", required=True, help="Directory to save packs")
    parser.add_argument("--lang", required=True, help="Language code")
    return parser.parse_args()

def main():
    args = parse_args()
    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    packs = {domain: [] for domain in DOMAINS}
    
    print(f"بدء استخلاص وتصنيف البيانات للغة: {args.lang}")
    with gzip.open(args.input, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            word = entry.get("word")
            pos = entry.get("pos")
            topics = entry.get("topics", [])
            categories = [c.get("name", "") if isinstance(c, dict) else str(c) for c in entry.get("categories", [])]
            tags = " ".join(topics + categories).lower()

            for domain, keywords in DOMAINS.items():
                if any(kw.lower() in tags for kw in keywords):
                    packs[domain].append({
                        "word": word,
                        "pos": pos,
                        "senses": [s.get("glosses", []) for s in entry.get("senses", [])],
                        "domain": domain
                    })

    for domain, items in packs.items():
        file_path = out_path / f"{args.lang}_{domain}.json"
        with open(file_path, "w", encoding="utf-8") as out:
            json.dump(items, out, ensure_ascii=False, indent=2)
        print(f"تم إنشاء حزمة {domain} بعدد {len(items)} مدخل.")

if __name__ == "__main__":
    main()
