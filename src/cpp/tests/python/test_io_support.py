"""Helpers shared by the io tests (not a test module)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from ref import golden, reference_available, ref_eval
from io_snippets import EXCHANGE_SNIPPET

import simplecadapi._cpp as scad


@pytest.fixture(scope="session")
def exchange_reference():
    """Numbers and file contents produced by the reference SDK (tests/golden/io_exchange_reference.json)."""
    return golden("io_exchange_reference", EXCHANGE_SNIPPET)


@pytest.fixture(scope="session")
def reference_shapes(exchange_reference, tmp_path_factory):
    """The reference SDK's box / cylinder / holed solids, imported from the STEP it wrote."""
    directory = tmp_path_factory.mktemp("reference_step")
    shapes = {}
    for name, record in exchange_reference.items():
        path = directory / f"{name}.step"
        path.write_bytes(base64.b64decode(record["step_b64"]))
        shapes[name] = scad.import_step(path)
    return shapes


def need_reference():
    if not reference_available():
        pytest.skip("the reference interpreter is not available")


__all__ = ["need_reference", "ref_eval"]
