import time
import json
from pathlib import Path
from standards.lexical.sqlite_v2 import build

def main():
    doc = json.loads(Path('standards/lexical/fixtures/positive.json').read_text())

    # artificially inflate the lexical_relations
    relations = doc.get('relations', [])
    if not relations:
        print("No relations found in fixture")
        return

    base_relation = relations[0]

    print("Inflating relations...")
    new_relations = []
    for i in range(50000):
        new_rel = dict(base_relation)
        new_rel['relation_id'] = f"rel_{i}"
        new_relations.append(new_rel)
    doc['relations'] = new_relations

    print(f"Testing with {len(doc['relations'])} relations")

    out = Path('test_perf.sqlite')
    if out.exists():
        out.unlink()

    start = time.time()
    build(doc, out)
    end = time.time()

    print(f"Time taken: {end - start:.4f} seconds")
    out.unlink()

if __name__ == '__main__':
    main()
