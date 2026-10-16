import json
from tools.visual_lexicon.api import ConceptRegistry

def main():
    registry = ConceptRegistry()
    with open('media/semantic_icons/fixture.json', 'r') as f:
        token_data = json.load(f)
    compressed = registry.register_concept(token_data)
    with open('media/semantic_icons/test_concept_1.vct', 'wb') as f:
        f.write(compressed)
    print("Fixture generated successfully.")

if __name__ == '__main__':
    main()
