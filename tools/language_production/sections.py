"""Map sense items onto the versioned section taxonomy through P31/P279 ancestors."""


def ancestors(qid, class_index, depth=6):
    """Return qid plus instance-of and subclass-of ancestors within depth hops."""
    if not isinstance(qid, str) or not qid:
        return set()
    seen = {qid}
    frontier = [qid]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            info = class_index.get(node) if isinstance(class_index, dict) else None
            if not isinstance(info, dict):
                continue
            for key in ('p31', 'p279'):
                parents = info.get(key) or []
                if not isinstance(parents, list):
                    continue
                for parent in parents:
                    if isinstance(parent, str) and parent not in seen:
                        seen.add(parent)
                        nxt.append(parent)
        if not nxt:
            break
        frontier = nxt
    return seen


def _best_section(item_qids, class_index, groups):
    """Pick the group whose class is closest to the sense item. Ties keep file order."""
    best = None
    best_hops = None
    best_order = None
    for order, group in enumerate(groups):
        classes = set(group.get('classes') or [])
        if not classes:
            continue
        for item in item_qids:
            found = ancestors(item, class_index)
            # Hops are not stored; closeness is the earliest ancestor generation.
            hops = _hops_to(item, classes, class_index)
            if hops is None:
                continue
            if best_hops is None or hops < best_hops or (hops == best_hops and order < best_order):
                best = group
                best_hops = hops
                best_order = order
                if hops == 0:
                    return best
    return best


def _hops_to(qid, classes, class_index, depth=6):
    if qid in classes:
        return 0
    seen = {qid}
    frontier = [qid]
    for hop in range(1, depth + 1):
        nxt = []
        for node in frontier:
            info = class_index.get(node) if isinstance(class_index, dict) else None
            if not isinstance(info, dict):
                continue
            parents = []
            for key in ('p31', 'p279'):
                parents.extend(info.get(key) or [])
            for parent in parents:
                if not isinstance(parent, str) or parent in seen:
                    continue
                if parent in classes:
                    return hop
                seen.add(parent)
                nxt.append(parent)
        frontier = nxt
        if not frontier:
            break
    return None


def pos_for(category, class_index, taxonomy):
    """Map a lexical category to a part of speech, including a class ancestor."""
    mapping = taxonomy.get('pos') or {}
    if not isinstance(category, str) or not isinstance(mapping, dict):
        return None
    best = None
    best_hops = None
    for qid, name in mapping.items():
        hops = _hops_to(category, {qid}, class_index or {})
        if hops is None:
            continue
        if best_hops is None or hops < best_hops:
            best = name
            best_hops = hops
            if hops == 0:
                return best
    return best


def section_for_items(item_qids, class_index, taxonomy):
    """Return a section id, or unclassified when no class claim supports one."""
    items = [item for item in item_qids if isinstance(item, str)]
    if not items:
        return 'unclassified'
    match = _best_section(items, class_index or {}, taxonomy.get('sections') or [])
    if match is None:
        return 'unclassified'
    return match['id']


def verb_subsection(category_qids, class_index, taxonomy):
    match = _best_section(list(category_qids or []), class_index or {}, taxonomy.get('verb_subsections') or [])
    if match is None:
        return None
    return match['id']
