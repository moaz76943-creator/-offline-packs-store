import os
import sys
import gzip
import json
import time
import argparse
import re
from pathlib import Path

MODEL_NAME = "gemini-3.1-pro-preview"
MAX_BATCH_SIZE = 25
LANG_CODE = re.compile(r"[a-z]{2,3}")


def call_gemini(prompt, api_key):
    for attempt in range(5):
        try:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=MODEL_NAME, contents=prompt)
                return res.text
            except ImportError:
                import google.generativeai as gai
                gai.configure(api_key=api_key)
                model = gai.GenerativeModel(MODEL_NAME)
                res = model.generate_content(prompt)
                return res.text
        except Exception as e:
            wait_time = (attempt + 1) * 5
            print(f"[Warning] API call failed: {e}. Retrying in {wait_time}s...", file=sys.stderr)
            time.sleep(wait_time)
    return None


def process_batch(batch, lang, api_key):
    prompt = f"""
    You are an expert lexicographer. Classify this list of {lang} words into:
    1. CEFR Level (A1, A2, B1, B2, C1, or C2)
    2. Primary Semantic Domain (e.g., travel, food, tech, business, medical, general, etc.)

    Input list:
    {json.dumps(batch, ensure_ascii=False)}

    Return ONLY a raw JSON array of objects with keys: "word", "cefr", "domain", "definition".
    No markdown backticks, no explanations.
    """
    response_text = call_gemini(prompt, api_key)
    if not response_text:
        print("[Error] Gemini returned an empty response.", file=sys.stderr)
        return None

    clean_text = response_text.strip()
    if clean_text.startswith("```"):
        clean_text = clean_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        print(f"[Error] Gemini response was not JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(parsed, list):
        print("[Error] Gemini response was not a JSON array.", file=sys.stderr)
        return None
    return parsed


def output_path_for(out_dir, lang, domain):
    safe_domain = re.sub(r"[^a-z0-9_-]", "", str(domain).lower()) or "general"
    path = (Path(out_dir) / f"{lang}_{safe_domain}.json").resolve()
    if path.parent != Path(out_dir).resolve():
        raise ValueError("refusing to write outside the output directory")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Classify a bounded dictionary sample with Gemini."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--lang", required=True)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_BATCH_SIZE,
        help=f"Maximum entries to classify this run (1-{MAX_BATCH_SIZE}).",
    )
    args = parser.parse_args(argv)

    if not LANG_CODE.fullmatch(args.lang):
        print("[Error] --lang must be a 2-3 letter language code.", file=sys.stderr)
        return 2
    if isinstance(args.batch_size, bool) or not isinstance(args.batch_size, int):
        print(f"[Error] --batch-size must be an integer from 1 to {MAX_BATCH_SIZE}.", file=sys.stderr)
        return 2
    if args.batch_size < 1 or args.batch_size > MAX_BATCH_SIZE:
        print(f"[Error] --batch-size must be an integer from 1 to {MAX_BATCH_SIZE}.", file=sys.stderr)
        return 2

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[Error] GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        return 1

    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    batch = []
    lines_read = 0
    malformed = 0

    print(f"[Start] Classifying at most {args.batch_size} {args.lang} entries using {MODEL_NAME}...")

    def gloss_of(entry):
        senses = entry.get("senses") or []
        if not senses or not isinstance(senses[0], dict):
            return ""
        glosses = senses[0].get("glosses") or []
        if not glosses or not isinstance(glosses[0], str):
            return ""
        return glosses[0]

    with gzip.open(args.input, "rt", encoding="utf-8") as handle:
        for line in handle:
            if lines_read >= args.batch_size:
                break
            lines_read += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed += 1
                print(f"[Warning] Skipping malformed line {lines_read}: {exc}", file=sys.stderr)
                continue
            if not isinstance(entry, dict):
                malformed += 1
                print(f"[Warning] Skipping non-object line {lines_read}.", file=sys.stderr)
                continue
            word = entry.get("word")
            if not isinstance(word, str) or not word:
                continue
            batch.append({"word": word, "definition": gloss_of(entry)})

    if not batch:
        print("[Error] No dictionary entries were available to classify.", file=sys.stderr)
        return 1

    results = process_batch(batch, args.lang, api_key)
    if not results:
        print("[Error] No usable classification was returned.", file=sys.stderr)
        return 1

    grouped = {}
    try:
        for item in results:
            if not isinstance(item, dict):
                continue
            target = output_path_for(out_path, args.lang, item.get("domain", "general"))
            grouped.setdefault(target.name, []).append(item)
    except ValueError as exc:
        print(f"[Error] {exc}", file=sys.stderr)
        return 1
    if not grouped:
        print("[Error] Gemini response contained no classification objects.", file=sys.stderr)
        return 1

    for name, items in grouped.items():
        with open(out_path.resolve() / name, "w", encoding="utf-8") as out_f:
            json.dump(items, out_f, ensure_ascii=False, indent=2)

    print(
        f"[Done] Wrote {len(grouped)} domain file(s) from {len(batch)} entries. "
        f"Malformed lines: {malformed}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
