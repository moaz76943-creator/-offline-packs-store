import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from tools.visual_lexicon.store import ConceptStore

def main():
    store = ConceptStore('media/semantic_icons')

    # Fixture 1: Apple
    apple_token = {
        'concept_id': 'food.fruit.apple',
        'version': 1,
        'viewBox': [0, 0, 100, 100],
        'paths': ['M 50 10 C 20 10 20 80 50 90 C 80 80 80 10 50 10 Z', 'M 50 10 Q 55 5 60 5'],
        'palette': ['#FF0000', '#00FF00'],
        'semantic_label': 'Red apple fruit with stem'
    }
    apple_manifest = {
        'concept_id': 'food.fruit.apple',
        'author': 'Original Vector Author',
        'source': 'https://example.com/cc0-apple',
        'license': 'CC0-1.0'
    }

    # Fixture 2: Bat (animal)
    bat_token = {
        'concept_id': 'animal.mammal.bat',
        'version': 1,
        'viewBox': [0, 0, 100, 100],
        'paths': ['M 10 50 Q 30 20 50 50 Q 70 20 90 50 Q 70 80 50 50 Q 30 80 10 50 Z'],
        'palette': ['#333333'],
        'semantic_label': 'Flying bat silhouette'
    }
    bat_manifest = {
        'concept_id': 'animal.mammal.bat',
        'author': 'Original Vector Author',
        'source': 'https://example.com/cc0-bat',
        'license': 'CC0-1.0'
    }

    store.add_token(apple_token['concept_id'], apple_token, apple_manifest)
    store.add_token(bat_token['concept_id'], bat_token, bat_manifest)
    print("Fixtures populated successfully in media/semantic_icons/")

if __name__ == '__main__':
    main()
