"""Heuristic CEFR labels. These are estimates, not corpus frequency bands."""

LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1')


def estimate_level(lemma, form_count, sense_count):
    """Return an estimated A1..C1 label from attested form/sense counts and length.

    More attested forms and a short lemma pull the estimate down. Many senses or a
    long lemma pull it up. This is not a frequency list and must stay labelled
    estimated.
    """
    lemma = lemma or ''
    form_count = int(form_count or 0)
    sense_count = int(sense_count or 0)
    length = len(lemma)
    if length <= 6 and form_count >= 4 and sense_count <= 2:
        level = 'A1'
    elif length <= 8 and form_count >= 2 and sense_count <= 3:
        level = 'A2'
    elif sense_count >= 5 or length >= 18:
        level = 'C1'
    elif sense_count >= 3 or length >= 12:
        level = 'B2'
    else:
        level = 'B1'
    if level not in LEVELS:
        level = 'B1'
    evidence = (
        f'estimated:heuristic-v1; forms={form_count}; senses={sense_count}; '
        f'lemma_length={length}; not a corpus frequency list'
    )
    return {
        'framework_id': 'cefr',
        'level_id': level,
        'evidence': evidence,
    }
