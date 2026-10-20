"""Content-policy filter shared by open-source adapters. Ambiguous or blocked items do not pass."""


def decide(text, qids, blocked_concepts, blocked_lemmas):
    """Return keep, exclude, or quarantine. Lemma matching is whole-token and case-insensitive."""
    for qid in qids or []:
        if qid in blocked_concepts:
            return 'exclude', 'blocked_concept'
    tokens = {token.casefold() for token in (text or '').split()}
    for lemma in blocked_lemmas or ():
        if lemma and lemma.casefold() in tokens:
            return 'quarantine', 'blocked_lemma'
    return 'keep', ''
