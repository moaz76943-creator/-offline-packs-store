"""Fill ratios for the organization catalog. Unfilled slots are gaps, never invented words."""

from tools.language_production.organization import display_hints, iter_concepts


def concept_inventory(graph):
    rows = []
    for section, subsection, concept in iter_concepts(graph):
        rows.append({
            'section': section['id'],
            'subsection': subsection['id'],
            'concept_id': concept['id'],
            'wikidata': concept['wikidata'],
        })
    return rows


def _applicable(slot, profile):
    rule = slot.get('applicability')
    if rule == 'all' or rule == 'source:tatoeba':
        return True
    if rule == 'unknown':
        return None
    if isinstance(rule, str) and rule.startswith('feature:'):
        feature = rule.split(':', 1)[1]
        state = (profile.get(feature) or profile.get('number') if feature == 'number' else profile.get(feature))
        if feature == 'number':
            state = profile.get('number')
        applicability = state.get('applicability') if isinstance(state, dict) else None
        if applicability == 'applicable':
            return True
        return None
    return None


def coverage_report(graph, frameworks, profiles, fills_by_language, *, sentences_approved=False):
    """fills_by_language maps a language id to a set of filled concept ids and grammar slot ids.

    A concept with no fill is a gap. Sentence slots stay gaps until the sentence source is
    approved, and even then they stay gaps until a real sentence is present. No lemma is created.
    """
    inventory = concept_inventory(graph)
    by_section = {}
    for row in inventory:
        by_section.setdefault(row['section'], []).append(row['concept_id'])
    languages = []
    for profile in profiles.get('languages') or []:
        language_id = profile.get('id')
        filled = fills_by_language.get(language_id) or {}
        concept_ids = set(filled.get('concepts') or [])
        grammar_ids = set(filled.get('grammar') or [])
        sections = []
        gap_count = 0
        filled_count = 0
        for section_id, concept_ids_in_section in by_section.items():
            have = [concept_id for concept_id in concept_ids_in_section if concept_id in concept_ids]
            missing = [concept_id for concept_id in concept_ids_in_section if concept_id not in concept_ids]
            filled_count += len(have)
            gap_count += len(missing)
            sections.append({
                'id': section_id,
                'filled': len(have),
                'gaps': len(missing),
                'fill_ratio': _ratio(len(have), len(concept_ids_in_section)),
                'gap_ids': missing,
            })
        levels = _level_coverage(frameworks, profile, grammar_ids, sentences_approved)
        total = filled_count + gap_count
        languages.append({
            'id': language_id,
            'filled_count': filled_count,
            'gap_count': gap_count,
            'fill_ratio': _ratio(filled_count, total),
            'display': display_hints(profile),
            'sections': sections,
            'levels': levels,
        })
    languages.sort(key=lambda row: (-row['gap_count'], row['id']))
    return {
        'schema_version': '1.0.0',
        'sentences_approved': bool(sentences_approved),
        'languages': languages,
    }


def _level_coverage(frameworks, profile, grammar_ids, sentences_approved):
    levels = []
    for level_id in frameworks.get('levels') or []:
        applicable = 0
        filled = 0
        gaps = []
        unknown = 0
        for track, slots in (frameworks.get('tracks') or {}).items():
            for slot in slots or []:
                if slot.get('level_id') != level_id:
                    continue
                state = _applicable(slot, profile)
                slot_id = slot.get('id')
                if state is None:
                    unknown += 1
                    continue
                if track == 'sentences' and not sentences_approved:
                    applicable += 1
                    gaps.append({'id': slot_id, 'status': 'gap', 'reason': 'sentence_source_not_approved'})
                    continue
                applicable += 1
                if slot_id in grammar_ids:
                    filled += 1
                else:
                    gaps.append({'id': slot_id, 'status': 'gap', 'reason': 'unfilled'})
        levels.append({
            'id': level_id,
            'filled': filled,
            'gaps': len(gaps),
            'unknown': unknown,
            'fill_ratio': _ratio(filled, applicable),
            'gap_slots': gaps,
        })
    return levels


def _ratio(filled, total):
    if not total:
        return 0.0
    return round(filled / total, 6)


def fills_from_summaries(summaries):
    """Read concept ids already harvested. Missing ids are not invented."""
    fills = {}
    for summary in summaries or []:
        if not isinstance(summary, dict) or not summary.get('id'):
            continue
        fills[summary['id']] = {
            'concepts': list(summary.get('concepts') or []),
            'grammar': list(summary.get('grammar_slots') or []),
        }
    return fills


def prioritize(report, limit=20):
    """Languages and sections with the most open concept gaps, largest first."""
    ranked = []
    for language in report.get('languages') or []:
        sections = sorted(language.get('sections') or [], key=lambda row: (-row.get('gaps', 0), row.get('id') or ''))
        ranked.append({
            'id': language.get('id'),
            'gap_count': language.get('gap_count') or 0,
            'fill_ratio': language.get('fill_ratio') or 0,
            'largest_section': sections[0]['id'] if sections else None,
            'largest_section_gaps': sections[0]['gaps'] if sections else 0,
        })
    ranked.sort(key=lambda row: (-row['gap_count'], row['fill_ratio'], row['id'] or ''))
    return ranked[:limit]
