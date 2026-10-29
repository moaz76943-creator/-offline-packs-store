import re
with open('tools/final_release_evidence/test_compiler.py', 'r') as f:
    content = f.read()

content = re.sub(
    r"\{'id': 'ar'\}, \{'id': 'ru'\}, \{'id': 'de'\}, \{'id': 'fr'\}, \{'id': 'es'\}",
    ", ".join([f"{{'id': 'l{i}'}}" for i in range(100)]),
    content
)

with open('tools/final_release_evidence/test_compiler.py', 'w') as f:
    f.write(content)
