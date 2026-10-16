import json
import csv
import sys
import os

def process_file(filepath):
    # Determine type of file based on extension
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.csv':
        process_csv(filepath, delimiter=',')
    elif ext == '.tsv':
        process_csv(filepath, delimiter='\t')
    else:
        print(f"Unsupported file type: {ext}")

def process_csv(filepath, delimiter):
    seen = set()
    cleaned_rows = []

    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            header = next(reader)
            cleaned_rows.append(header)

            # Find indices for word, translation, and level
            word_idx = -1
            trans_idx = -1
            level_idx = -1

            for i, col in enumerate(header):
                col_lower = col.lower()
                if 'word' in col_lower or 'source' in col_lower:
                    word_idx = i
                elif 'translation' in col_lower or 'target' in col_lower:
                    trans_idx = i
                elif 'level' in col_lower or 'cefr' in col_lower:
                    level_idx = i

            if word_idx == -1 or trans_idx == -1 or level_idx == -1:
                print(f"Warning: Could not find required columns in {filepath}. Using indices 0, 1, 2 if available.")
                word_idx = 0
                trans_idx = 1
                level_idx = 2

            for row in reader:
                if len(row) <= max(word_idx, trans_idx, level_idx):
                    cleaned_rows.append(row)
                    continue

                word = row[word_idx].strip()
                trans = row[trans_idx].strip()
                level = row[level_idx].strip()

                key = (word, trans, level)
                if key not in seen:
                    seen.add(key)
                    cleaned_rows.append(row)

        except StopIteration:
            pass

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerows(cleaned_rows)
    print(f"Processed {filepath}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/remove_duplicates.py <path_to_directory>")
        sys.exit(1)

    directory = sys.argv[1]

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.csv') or file.endswith('.tsv'):
                process_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
