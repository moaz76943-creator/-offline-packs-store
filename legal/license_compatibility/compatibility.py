import sys
from pathlib import Path

# Add legal/ledger to sys.path to reuse admission.py
ledger_path = Path(__file__).resolve().parent.parent / 'ledger'
if str(ledger_path) not in sys.path:
    sys.path.append(str(ledger_path))

from admission import LICENSES, OBLIGATIONS


def check_compatibility(sources, output_license, is_derivative=True):
    """
    Check if combining the given sources into the output license is compatible.

    Args:
        sources (list of dict): List of source dictionaries. Each must have a 'license' dict
                                with at least an 'id' string.
        output_license (str): The desired output license id.
        is_derivative (bool): True if this is a derivative work, False if a mere aggregation.

    Returns:
        dict: containing:
            'status': 'COMPATIBLE', 'INCOMPATIBLE', or 'REVIEW_REQUIRED'
            'reason': explanation of the decision
            'obligations': set of obligations accumulated
    """
    if output_license not in LICENSES:
        return {'status': 'REVIEW_REQUIRED', 'reason': f'unsupported output license {output_license}', 'obligations': set()}

    obligations = set()
    copyleft = set()

    for source in sources:
        lic = source.get('license', {})
        lid = lic.get('id')

        if not lid:
            return {'status': 'INCOMPATIBLE', 'reason': 'missing source license', 'obligations': set()}

        if lid not in LICENSES:
            return {'status': 'REVIEW_REQUIRED', 'reason': f'unknown source license {lid}', 'obligations': set()}

        if lid in ('CC-BY-SA-4.0', 'GFDL-1.3-only'):
            copyleft.add(lid)

        obligations.update(OBLIGATIONS.get(lid, set()))

        if lid == 'CC0-1.0' and output_license == 'PUBLIC-DOMAIN':
            return {'status': 'INCOMPATIBLE', 'reason': 'CC0 is not a blanket public-domain claim', 'obligations': set()}

    if sources and output_license == 'PUBLIC-DOMAIN' and any(
            s.get('license', {}).get('id') != 'PUBLIC-DOMAIN' for s in sources):
        return {'status': 'INCOMPATIBLE', 'reason': 'public-domain label contradicts original rights', 'obligations': set()}

    if is_derivative:
        if len(copyleft) > 1:
            return {'status': 'INCOMPATIBLE', 'reason': 'GFDL and CC BY-SA cannot be assumed interchangeable in derivative works', 'obligations': set()}

        if copyleft:
            required_license = next(iter(copyleft))
            if output_license != required_license:
                return {'status': 'INCOMPATIBLE', 'reason': f'source cannot be relicensed to {output_license}', 'obligations': set()}
    else:
        # For pure aggregation, copyleft licenses do not infect the whole collection,
        # but the collection itself cannot be licensed under a unified copyleft license
        # that contradicts the parts unless it's just the collection license.
        # But we must track obligations.
        pass

    return {'status': 'COMPATIBLE', 'reason': 'passed compatibility checks', 'obligations': obligations}
