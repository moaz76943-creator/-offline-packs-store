import os
import sys
import gzip
import json
import time
import argparse
from pathlib import Path

MODEL_NAME = "gemini-2.5-pro"

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
            print(f"[Warning] API call failed: {e}. Retrying in {wait_time}s...")
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
        return []
    
    clean_text = response_text.strip()
    if clean_text.startswith("```"):
        clean_text = clean_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    
    try:
        return json.loads(clean_text)
    except Exception:
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--lang", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[Error] GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    out_path = Path(args.out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    classified_data = {}
    batch = []
    batch_size = 25
    processed_count = 0

    print(f"[Start] Processing {args.lang} dictionary using {MODEL_NAME}...")

    with gzip.open(args.input, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                word = entry.get("word")
                if not word:
                    continue
                
                senses = entry.get("senses", [])
                gloss = senses[0].get("glosses", [""])[0] if senses else ""
                batch.append({"word": word, "definition": gloss})

                if len(batch) >= batch_size:
                    results = process_batch(batch, args.lang, api_key)
                    for item in results:
                        domain = item.get("domain", "general").lower()
                        classified_data.setdefault(domain, []).append(item)
                    
                    processed_count += len(batch)
                    print(f"[Progress] Processed {processed_count} words...")
                    batch = []
                    time.sleep(2)

                    # حفظ مرحلي للملفات
                    for domain, items in classified_data.items():
                        with open(out_path / f"{args.lang}_{domain}.json", "w", encoding="utf-8") as out_f:
                            json.dump(items, out_f, ensure_ascii=False, indent=2)

            except Exception as e:
                continue

    print(f"[Done] Finished categorization into {len(classified_data)} domains.")

if __name__ == "__main__":
    main()
