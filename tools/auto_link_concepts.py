#!/usr/bin/env python3
import os
import csv
import glob
import hashlib
import sys

def scan_and_link_tsvs(directory="."):
    """Scan multi-language TSV files, group by English translation, assign shared Concept_ID."""
    tsv_files = glob.glob(os.path.join(directory, "**/*.tsv"), recursive=True)
    if not tsv_files:
        print("No TSV files found.")
        return

    # Dictionary to hold the shared Concept_ID for each exact English translation
    # { "english translation": "C_12345678" }
    translation_to_concept = {}

    # We will read all data into memory for simplicity
    file_data_map = {}

    for file_path in tsv_files:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            fieldnames = reader.fieldnames
            if not fieldnames:
                continue

            en_col = None
            for col in fieldnames:
                if col.lower() in ['english', 'en', 'english translation', 'translation_en', 'english_translation', 'translation']:
                    en_col = col
                    break

            if not en_col:
                print(f"Skipping {file_path}: No English column found.")
                continue

            if 'Concept_ID' not in fieldnames:
                fieldnames.append('Concept_ID')

            rows = list(reader)
            file_data_map[file_path] = {
                'fieldnames': fieldnames,
                'rows': rows,
                'en_col': en_col
            }

            # First pass: map English translation to Concept_IDs if already exists, else generate one
            for row in rows:
                en_text = row.get(en_col, '')
                if en_text is None:
                    continue
                en_text = en_text.strip()
                if not en_text:
                    continue

                existing_concept_id = row.get('Concept_ID', '')
                if existing_concept_id is None:
                    existing_concept_id = ''
                existing_concept_id = existing_concept_id.strip()

                if en_text not in translation_to_concept:
                    if existing_concept_id:
                        translation_to_concept[en_text] = existing_concept_id
                    else:
                        # Generate a deterministic ID based on the english translation hash
                        hash_val = hashlib.md5(en_text.lower().encode('utf-8')).hexdigest()[:8].upper()
                        translation_to_concept[en_text] = f"C_{hash_val}"

    # Second pass: Update rows and write back
    for file_path, data in file_data_map.items():
        rows = data['rows']
        en_col = data['en_col']
        fieldnames = data['fieldnames']

        updated_rows = []
        for row in rows:
            en_text = row.get(en_col, '')
            if en_text is None:
                en_text = ''
            en_text = en_text.strip()

            if en_text:
                row['Concept_ID'] = translation_to_concept[en_text]
            else:
                if 'Concept_ID' not in row or row['Concept_ID'] is None:
                    row['Concept_ID'] = ''
            updated_rows.append(row)

        # write back
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t')
            writer.writeheader()
            writer.writerows(updated_rows)

        print(f"Successfully processed and auto-linked Concept IDs in: {file_path}")

if __name__ == "__main__":
    scan_and_link_tsvs(sys.argv[1] if len(sys.argv) > 1 else ".")
