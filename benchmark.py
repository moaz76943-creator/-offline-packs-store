import time
import sys
from pathlib import Path

# Add the standard/lexical directory to python path
sys.path.insert(0, str(Path(__file__).parent / 'standards' / 'lexical'))

from sqlite_v2 import build

def create_large_document():
    doc = {
        "contract_version": "1.0.0",
        "document_id": "test_doc",
        "lexemes": [],
        "senses": [],
        "translations": [],
        "examples": [],
        "relations": []
    }

    for i in range(10000):
        doc["lexemes"].append({
            "lexeme_id": f"lex_en_{i}",
            "surface": f"word_{i}",
            "pos": "noun",
            "direction": "ltr",
            "language": "en",
            "script": "Latn",
            "lemma": f"word_{i}",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_{i}",
                "fixture_only": True
            }
        })
        doc["lexemes"].append({
            "lexeme_id": f"lex_es_{i}",
            "surface": f"palabra_{i}",
            "pos": "noun",
            "direction": "ltr",
            "language": "es",
            "script": "Latn",
            "lemma": f"palabra_{i}",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_es_{i}",
                "fixture_only": True
            }
        })
        doc["senses"].append({
            "sense_id": f"sense_en_{i}",
            "lexeme_id": f"lex_en_{i}",
            "concept_id": f"concept_{i%100}",
            "definition": f"definition_{i}",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_{i}",
                "fixture_only": True
            }
        })
        doc["senses"].append({
            "sense_id": f"sense_es_{i}",
            "lexeme_id": f"lex_es_{i}",
            "concept_id": f"concept_{i%100}",
            "definition": f"definición_{i}",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_es_{i}",
                "fixture_only": True
            }
        })
        doc["translations"].append({
            "translation_id": f"trans_es_{i}",
            "from_sense_id": f"sense_en_{i}",
            "to_sense_id": f"sense_es_{i}",
            "language": "es",
            "text": f"palabra_{i}",
            "equivalence": "exact",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_{i}",
                "fixture_only": True
            }
        })
        doc["examples"].append({
            "example_id": f"ex_en_{i}",
            "sense_id": f"sense_en_{i}",
            "language": "en",
            "script": "Latn",
            "text": f"This is word_{i}",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_{i}",
                "fixture_only": True
            }
        })
        doc["relations"].append({
            "relation_id": f"rel_en_{i}",
            "from_lexeme_id": f"lex_en_{i}",
            "to_lexeme_id": f"lex_en_{(i+1)%5000}",
            "kind": "variant",
            "source": {
                "publication_approved": True,
                "retrieval_id": "some_id",
                "source_id": "src_id",
                "origin_url": "https://example.com",
                "publisher": "Test Publisher",
                "dataset_version": "1.0.0",
                "license_id": "CC-BY-4.0",
                "record_locator": f"loc_{i}",
                "fixture_only": True
            }
        })
    return doc

def main():
    doc = create_large_document()
    output_path = Path("test_output.sqlite")
    if output_path.exists():
        output_path.unlink()

    start_time = time.time()
    try:
        build(doc, output_path, publication=False)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return

    duration = time.time() - start_time
    print(f"Time taken: {duration:.4f} seconds")

    # Store baseline
    with open("baseline.txt", "w") as f:
        f.write(str(duration))

if __name__ == "__main__":
    main()
