"""Write synthetic vector fixtures. These are not licensed assets and cite no source."""
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
            'semantic_label': 'Apple outline',
            'alt_text': 'A simple outline of an apple',
        },
        'manifest': {
            'concept_id': 'food.fruit.apple',
            'author': 'Fixture Author',
            'license': 'CC0-1.0',
            'source': 'https://example.com/cc0-apple',
        },
    },
    {
        'token': {
            'concept_id': 'animal.mammal.bat',
            'version': 1,
            'viewBox': [0, 0, 100, 100],
            'paths': ['M 10 50 Q 30 20 50 50 Q 70 20 90 50 Q 70 80 50 50 Q 30 80 10 50 Z'],
            'palette': ['#333333'],
            'semantic_label': 'Bat outline',
            'alt_text': 'A simple outline of a bat',
        },
        'manifest': {
            'concept_id': 'animal.mammal.bat',
            'author': 'Fixture Author',
            'license': 'CC0-1.0',
            'source': 'https://example.com/cc0-bat',
        },
    },
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True,
                        help='Directory for synthetic fixtures. Not a publication path.')
    args = parser.parse_args(argv)
    store = ConceptStore(args.out)
    for item in FIXTURES:
        store.add_token(item['token']['concept_id'], item['token'], item['manifest'])
    print(f'synthetic fixtures written under {args.out}')


if __name__ == '__main__':
    main()
