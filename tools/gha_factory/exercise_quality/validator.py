"""Evidence-preserving Cloze replay QA for GHA-05 (no publication)."""
from __future__ import annotations

import hashlib
import json
import unicodedata

from tools.gha_factory.examples.factory import Rejected, make_cloze


class ExerciseError(ValueError):
    """Missing or conflicting source-backed educational exercise evidence."""


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def verify_cloze(exercise, sentence, annotation, senses, forms, languages):
    """Replay canonical GHA-05 maker; output remains a candidate under review.

    Only independent sentence, morphology and editorial evidence may produce a
    candidate. The function never upgrades it to approved learning content.
    """
    if not isinstance(exercise, dict) or not isinstance(sentence, dict) or not isinstance(annotation, dict):
        raise ExerciseError('INVALID_EVIDENCE_ENVELOPE')
    if not isinstance(languages, set) or sentence.get('language') not in languages:
        raise ExerciseError('UNREGISTERED_LANGUAGE')
    if sentence.get('admitted') is not True:
        raise ExerciseError('UNADMITTED_SENTENCE')
    if sentence.get('license') != 'CC0-1.0':
        raise ExerciseError('LICENSE_REVIEW_REQUIRED')
    if not isinstance(sentence.get('text'), str) or not sentence['text'].strip():
        raise ExerciseError('INVALID_ORIGINAL_TEXT')
    if sentence.get('source_sha256') is None or not isinstance(sentence['source_sha256'], str) or len(sentence['source_sha256']) != 64 or not all(c in '0123456789abcdef' for c in sentence['source_sha256']):
        raise ExerciseError('MISSING_SOURCE_SNAPSHOT_SHA')
    if not isinstance(sentence.get('attribution'), str) or not sentence['attribution'].startswith('https://'):
        raise ExerciseError('MISSING_ATTRIBUTION')
    if annotation.get('source_sha256') != sentence['source_sha256']:
        raise ExerciseError('ANNOTATION_SOURCE_MISMATCH')
    try:
        rebuilt = make_cloze(sentence, annotation, senses, forms)
    except (Rejected, KeyError, TypeError, ValueError) as exc:
        raise ExerciseError('GHA05_EVIDENCE_GATE_REJECTED') from exc
    if set(exercise) != set(rebuilt) or _canonical(exercise) != _canonical(rebuilt):
        raise ExerciseError('CANDIDATE_TAMPERED_OR_STALE')
    if exercise.get('status') != 'VERIFIED_CANDIDATE_NOT_PUBLISHED':
        raise ExerciseError('INVALID_CANDIDATE_STATUS')
    if len(exercise['options']) != len(set(x.casefold() for x in exercise['options'])):
        raise ExerciseError('DUPLICATE_CHOICES')
    return {'exercise_id': rebuilt['exercise_id'], 'language': sentence['language'],
            'source_sha256': sentence['source_sha256'],
            'candidate_sha256': hashlib.sha256(_canonical(rebuilt)).hexdigest(),
            'quality_status': 'REVIEW_REQUIRED', 'publication_approved': False,
            'semantic_uniqueness_independently_verified': False}


def evaluate_response(answer, accepted_answers, attested_alternates=frozenset()):
    """No guessed morphology, spell-correction or dialect exclusion.

    Accepted answers must be editorially attested before this call; a merely
    similar or one-edit form does not prove orthographic or grammar error.
    """
    if not isinstance(answer, str) or not isinstance(accepted_answers, (set, frozenset)) or not accepted_answers or any(not isinstance(x, str) or not x for x in accepted_answers):
        raise ExerciseError('INVALID_ANSWER_EVIDENCE')
    if not isinstance(attested_alternates, (set, frozenset)) or any(not isinstance(x, str) or not x for x in attested_alternates):
        raise ExerciseError('INVALID_ALTERNATE_EVIDENCE')
    if accepted_answers & attested_alternates:
        raise ExerciseError('CONFLICTING_ANSWER_EVIDENCE')
    if answer in accepted_answers:
        return 'CORRECT'
    if unicodedata.normalize('NFC', answer) in {unicodedata.normalize('NFC', x) for x in accepted_answers}:
        return 'CORRECT'
    if answer in attested_alternates:
        return 'AMBIGUOUS'
    return 'UNVERIFIED'
