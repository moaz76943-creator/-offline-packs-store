"""Fixture ingestion pipeline.

The admission gate runs before the publish step. A blocked gate must not
create or publish the downstream artifact. This module is the executable
fixture for that halt; it does not claim a production workflow invokes it.
"""
from pathlib import Path

try:
    from tools.ingestion_circuit_breaker.gate import process
except ImportError:
    from gate import process


def run_fixture_pipeline(args, publish_path, payload):
    """Admit via the gate, then write payload only when admission succeeds.

    Returns (code, errors, published). published is false when the gate
    blocks, and publish_path is left uncreated.
    """
    code, errors = process(args)
    if code != 0:
        return code, errors, False
    destination = Path(publish_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return code, errors, True
