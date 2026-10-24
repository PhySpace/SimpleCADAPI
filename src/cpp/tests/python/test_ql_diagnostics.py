"""QL selection-trust diagnosis: ports of the QL cases of the reference test_error_diagnostics_blend_ql.py.

The rendered-evidence assertions of the original need a renderer; here the evidence hook is
checked with a stand-in provider (see test_ql_golden.py for the argument contract).
"""

from __future__ import annotations

import pytest

import simplecadapi._cpp as scad
from simplecadapi._cpp import ql
from simplecadapi._cpp.ql import _testing as raw


def split_band_solid():
    rod = raw.cylinder_at((0, 0, 0), 10, 20)
    ring = raw.cylinder_at((0, 0, 7), 12, 6)
    inner = raw.cylinder_at((0, 0, 5), 9, 10)
    return raw.cut(rod, raw.cut(ring, inner))


def payload(error) -> dict:
    return error.to_dict()


def test_ql_ambiguity_reports_split_surface_group():
    part = split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        ql.faces().where(ql.surface_type("CYLINDER")).exactly(1).resolve(part)

    data = payload(ctx.value)
    assert data["operation"] == "ql.face.resolve"
    assert "expected exactly 1 face(s), got 3" in data["what_happened"]
    assert "logical surface group" in data["what_happened"]
    # The two r=10 bands are named as one logical group in the repair.
    assert any("lie on one logical surface" in step and "F1+F6" in step for step in data["repair"])
    inventory = data["inventory"]
    hits = [entry for entry in inventory if entry["status"] == "hit"]
    assert len(hits) == 3
    # Split pieces of one surface are distinguishable by their axial span.
    spans = [entry["description"] for entry in hits if "r=10" in entry["description"]]
    assert len(spans) == 2
    assert spans[0] != spans[1]
    assert any("z=[" in text for text in spans)
    # Near-misses describe what else exists (the planes).
    assert any("plane" in entry["description"] for entry in inventory)


def test_ql_zero_hit_lists_near_miss_inventory():
    part = split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        ql.faces().where(ql.surface_type("SPHERE")).at_least(1).resolve(part)

    data = payload(ctx.value)
    assert "expected at least 1 face(s), got 0" in data["what_happened"]
    inventory = data["inventory"]
    assert all(entry["status"] == "near_miss" for entry in inventory)
    assert any("cylinder r=10" in entry["description"] for entry in inventory)
    assert any("align predicate values" in step for step in data["repair"])


def test_error_text_is_the_agent_facing_message():
    part = split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        ql.faces().where(ql.surface_type("CYLINDER")).exactly(1).resolve(part)
    text = str(ctx.value)
    assert text.startswith("Operation: ql.face.resolve\n")
    assert "Documentation: For full usage details, run help(ql.face.resolve)." in text
    assert "Measurements:\n- matched_count: 3\n- candidate_count: 7\n- expected_count: 1" in text
    assert "Inventory:\n- F1 [hit] cylinder r=10, axis (0,0,1) @ (0,0,0), spans z=[13, 20]" in text
    assert isinstance(ctx.value, ValueError)


def test_ql_highlight_does_not_pollute_user_shape():
    part = split_band_solid()

    def all_tags():
        return {tag for face in ql.faces().resolve(part) for tag in face._list_tags()}

    before = all_tags()
    with pytest.raises(scad.SimpleCADError):
        ql.faces().where(ql.surface_type("CYLINDER")).exactly(1).resolve(part)
    after = all_tags()
    assert before == after
    assert all("diagnostic" not in tag for tag in after)


def test_evidence_provider_failures_never_mask_the_error():
    def broken(scope, matched, kind, key, near):
        raise RuntimeError("renderer is down")

    ql._set_evidence_provider(broken)
    try:
        with pytest.raises(scad.SimpleCADError) as ctx:
            ql.faces().exactly(0).resolve(split_band_solid())
    finally:
        ql._set_evidence_provider(None)
    assert ctx.value.to_dict()["evidence"] == []
    assert "expected exactly 0 face(s), got 7" in ctx.value.to_dict()["what_happened"]


def test_unrelated_python_exceptions_in_resolvers_propagate():
    face = ql.faces().resolve(raw.box_at((0, 0, 0), 1, 1, 1))[0]

    def resolver(shape, path):
        raise KeyError("boom")

    ql.register_property_resolver("explode.", resolver)
    try:
        with pytest.raises(KeyError):
            ql.prop("explode.now", "==", 1)(face)
    finally:
        ql.unregister_property_resolver("explode.")
