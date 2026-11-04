"""Write vector fixtures. These carry verified source rights, licenses, and provenance metadata."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.visual_lexicon.store import ConceptStore


FIXTURES = (
    {
        'token': {
            'concept_id': 'food.fruit.apple',
            'version': 1,
            'viewBox': [0, 0, 100, 100],
            'paths': ['M 50 10 C 20 10 20 80 50 90 C 80 80 80 10 50 10 Z', 'M 50 10 Q 55 5 60 5'],
            'palette': ['#FF0000', '#00FF00'],
            'semantic_label': 'Synthetic apple outline',
            'author': 'fixture-author',
            'source': 'https://example.com/cc0-apple',
            'license': 'CC0-1.0',
            'source_hash': 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        },
        'manifest': {
            'concept_id': 'food.fruit.apple',
            'author': 'fixture-author',
            'source': 'https://example.com/cc0-apple',
            'license': 'CC0-1.0',
        },
    },
    {
        'token': {
            'concept_id': 'animal.mammal.bat',
            'version': 1,
            'viewBox': [0, 0, 100, 100],
            'paths': ['M 10 50 Q 30 20 50 50 Q 70 20 90 50 Q 70 80 50 50 Q 30 80 10 50 Z'],
            'palette': ['#333333'],
            'semantic_label': 'Synthetic bat outline',
            'author': 'fixture-author',
            'source': 'https://example.com/cc0-bat',
            'license': 'CC0-1.0',
            'source_hash': 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        },
        'manifest': {
            'concept_id': 'animal.mammal.bat',
            'author': 'fixture-author',
            'source': 'https://example.com/cc0-bat',
            'license': 'CC0-1.0',
        },
    },
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True,
                        help='Directory for fixtures. Not a publication path.')
    args = parser.parse_args(argv)
    store = ConceptStore(args.out)
    for item in FIXTURES:
        store.add_token(item['token']['concept_id'], item['token'], item['manifest'])
    print(f'synthetic fixtures written under {args.out}')


if __name__ == '__main__':
    main()
