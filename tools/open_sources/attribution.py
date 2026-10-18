"""Write the attribution file for one source. This does not admit the source to the ledger."""


def render_attribution(source, *, record_count, changes):
    attribution = source.get('attribution') or {}
    creators = attribution.get('creators') or ['unspecified']
    lines = [
        f"Title: {attribution.get('title') or source.get('id')}",
        f"Creators: {', '.join(creators)}",
        f"Source: {attribution.get('source_url') or source.get('origin_url')}",
        f"Via: {attribution.get('via') or source.get('id')}",
        f"Stated license: {source.get('stated_license') or 'unverified'}",
        f"Ledger license: {source.get('declared_license') or 'none'}",
        f"License evidence: {source.get('evidence_path') or 'none'}",
        f"Evidence sha256: {source.get('evidence_sha256') or 'none'}",
        f"Retrieved: {source.get('retrieved') or 'see catalog/organization/sources.v1.json'}",
        f"Records: {int(record_count)}",
        f"Changes: {changes}",
        "publication_approved: false",
        "This attribution file is generated from the source catalog. It is not a ledger admission.",
        "",
    ]
    return "\n".join(lines)
