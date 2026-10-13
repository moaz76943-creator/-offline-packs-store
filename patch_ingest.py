import sys
from pathlib import Path

file_path = Path('community/contributions/ingest.py')
content = file_path.read_text(encoding='utf-8')

# Update ALLOWED_EXTENSIONS to not include tsv since we don't have tsv support yet.
content = content.replace(
    "ALLOWED_EXTENSIONS = {'.json', '.jsonl', '.tsv', '.gz', '.zip', '.tar.gz', '.tgz'}",
    "ALLOWED_EXTENSIONS = {'.json', '.jsonl', '.gz', '.zip', '.tar.gz', '.tgz'}"
)

# Update rglob to only target .json and .jsonl files
content = content.replace(
    "for file_in_bundle in temp_path.rglob('*'):",
    "for file_in_bundle in temp_path.rglob('*'):\n                if file_in_bundle.suffix not in ['.json', '.jsonl']:\n                    continue"
)

file_path.write_text(content, encoding='utf-8')
