"""Fillet/chamfer degeneration taxonomy and QL selection-trust diagnosis.

One case per failure family from the accumulated degeneration catalog
(repo history + OCC ecosystem): size vs face room, tangent adjacency,
tangency-critical interaction, bore curvature, and the QL cardinality
inventory with logical-surface grouping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.operators._diagnostics import _RENDER_DEDUP


@pytest.fixture(autouse=True)
def _no_render(monkeypatch):
    monkeypatch.setenv("SCA_NO_DIAGNOSTIC_RENDER", "1")


def _box() -> scad.Solid:
    return scad.make_box_rsolid(10, 10, 10)


def _box_edges(solid):
    return scad.ql.edges().resolve(solid)


def _payload(error) -> dict:
    return error.to_dict()


def test_chamfer_distance_exceeds_face_room():
    box = _box()
    edges = _box_edges(box)
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.chamfer_rsolid(box, [edges[0]], 12)

    payload = _payload(ctx.value)
    assert "distance 12 mm meets or exceeds the 10 mm" in payload["what_happened"]
    measurements = {m["name"]: m["value"] for m in payload["measurements"]}
    assert measurements["available_face_room"] == pytest.approx(10.0)
    assert any("below 10 mm" in step for step in payload["repair"])


def test_fillet_radius_exceeds_face_room():
    box = _box()
    edges = _box_edges(box)
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(box, [edges[0]], 12)

    payload = _payload(ctx.value)
    assert "radius 12 mm meets or exceeds the 10 mm" in payload["what_happened"]
    measurements = {m["name"]: m["value"] for m in payload["measurements"]}
    assert measurements["radius"] == pytest.approx(12.0)


def _slot_solid() -> scad.Solid:
    arc_left = scad.make_three_point_arc_redge((0, 5, 0), (-5, 0, 0), (0, -5, 0))
    line_bottom = scad.make_segment_redge((0, -5, 0), (20, -5, 0))
    arc_right = scad.make_three_point_arc_redge((20, -5, 0), (25, 0, 0), (20, 5, 0))
    line_top = scad.make_segment_redge((20, 5, 0), (0, 5, 0))
    wire = scad.make_wire_from_edges_rwire([arc_left, line_bottom, arc_right, line_top])
    return scad.extrude_rsolid(scad.make_face_from_wire_rface(wire), (0, 0, 1), 8)


def test_fillet_tangent_adjacent_faces_degenerates():
    solid = _slot_solid()
    junction = None
    for edge in scad.ql.edges().resolve(solid):
        p1 = edge.get_start_vertex().get_coordinates()
        p2 = edge.get_end_vertex().get_coordinates()
        mid = tuple((a + b) / 2 for a, b in zip(p1, p2))
        if abs(mid[0]) < 1e-6 and abs(mid[1] - 5) < 1e-6:
            junction = edge
            break
    assert junction is not None

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(solid, [junction], 1.0)

    payload = _payload(ctx.value)
    assert "already tangent" in payload["what_happened"]
    measurements = {m["name"]: m["value"] for m in payload["measurements"]}
    assert measurements["dihedral_angle"] == pytest.approx(180.0, abs=0.5)
    assert any("no corner to blend" in step for step in payload["repair"])


def test_fillet_tangency_critical_all_edges():
    box = _box()
    edges = _box_edges(box)
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(box, edges, 5)

    payload = _payload(ctx.value)
    assert "meet tangentially" in payload["what_happened"]
    measurements = {m["name"]: m["value"] for m in payload["measurements"]}
    assert measurements["combined_blend_width"] == pytest.approx(10.0)
    assert measurements["available_face_room"] == pytest.approx(10.0)
    assert any("below 5 mm" in step for step in payload["repair"])


def test_fillet_bore_mouth_boundary_room():
    # Tube: outer r=10 with a bore r=4 leaves a 6 mm annulus. Empirically
    # OCC accepts r=5 but fails at r=6 == annulus width: the boundary case
    # degenerates the top-face strip, and the room probe must say so.
    outer = scad.make_cylinder_rsolid(10, 10)
    bore = scad.make_cylinder_rsolid(4, 20, bottom_face_center=(0, 0, -5))
    tube = scad.cut_rsolid(outer, bore)
    mouth_edges = [
        edge
        for edge in scad.ql.edges().resolve(tube)
        if abs(edge.get_start_vertex().get_coordinates()[2]
               - edge.get_end_vertex().get_coordinates()[2]) < 1e-6
        and edge.get_start_vertex().get_coordinates()[2] > 9.0
    ]
    assert mouth_edges

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(tube, mouth_edges, 6)

    payload = _payload(ctx.value)
    assert "meets or exceeds" in payload["what_happened"]
    measurements = {m["name"]: m["value"] for m in payload["measurements"]}
    assert measurements["available_face_room"] == pytest.approx(6.0)
    assert any("below 6 mm" in step for step in payload["repair"])


def test_fillet_silent_garbage_output_caught_at_exit():
    # Mechanism E: r=5 on all 12 edges of a 10-cube fails loudly, but r=6
    # makes the kernel *succeed* and hand back a degenerate solid. Geometrically
    # impossible; the exit check must name it instead of returning it.
    box = _box()
    edges = _box_edges(box)
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(box, edges, 6)

    payload = _payload(ctx.value)
    what = payload["what_happened"]
    # The volume violation leads what_happened so the agent can tell
    # "kernel silently lied" apart from "kernel refused" (r=5 path). How the
    # garbage solid measures depends on the volume integrator: the fixed-order
    # one reported phantom extra material (~1036 on macOS, ~1039 on Linux, more
    # than the 1000 it was given); the knot-span (Gauss-Kronrod) one sees an
    # empty solid (volume 0). Either way the exit check must name it.
    garbage = re.search(r"result volume (?:is )?([0-9.]+)", what)
    assert garbage, what
    volume = float(garbage.group(1))
    if volume > 1000:
        assert "exceeds the input volume 1000" in what
    else:
        assert volume == 0.0
        assert "empty/degenerate solid" in what
    # Probe explanation follows as the suspected root cause.
    assert "probes indicate" in what
    assert "BlendVolumeViolation" in (payload["technical_details"] or "")


def test_legit_fillet_passes_exit_check():
    # No false positives: an ordinary fillet must pass the monotonic-volume
    # guard untouched.
    box = _box()
    edges = _box_edges(box)
    result = scad.fillet_rsolid(box, [edges[0]], 1)
    assert len(result._iter_faces()) >= 6


def test_concave_edge_fillet_may_add_material():
    # Regression: a bolt's underhead fillet rounds a concave (270°) edge,
    # and the corner fill legitimately ADDS material — observed as exactly
    # the quarter-circle deficit times the circumference (+1.28 mm³ on the
    # d=8 bolt). Mechanism E must skip the increase check for concave
    # selections, not call the kernel a liar.
    bolt = scad.std.fastener.make_bolt_rsolid(diameter=8.0, length=24.0)
    assert isinstance(bolt, scad.Solid)


def _split_band_solid() -> scad.Solid:
    cylinder = scad.make_cylinder_rsolid(10, 20)
    ring = scad.make_cylinder_rsolid(12, 6, bottom_face_center=(0, 0, 7))
    inner = scad.make_cylinder_rsolid(9, 10, bottom_face_center=(0, 0, 5))
    return scad.cut_rsolid(cylinder, scad.cut_rsolid(ring, inner))


def test_ql_ambiguity_reports_split_surface_group():
    part = _split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.ql.faces().where(scad.ql.surface_type("CYLINDER")).exactly(1).resolve(part)

    payload = _payload(ctx.value)
    assert "expected exactly 1 face(s), got 3" in payload["what_happened"]
    assert "logical surface group" in payload["what_happened"]
    # The two r=10 bands are named as one logical group in the repair.
    assert any(
        "lie on one logical surface" in step and "F1+F6" in step
        for step in payload["repair"]
    )
    inventory = payload["inventory"]
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
    part = _split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.ql.faces().where(scad.ql.surface_type("SPHERE")).at_least(1).resolve(part)

    payload = _payload(ctx.value)
    assert "expected at least 1 face(s), got 0" in payload["what_happened"]
    inventory = payload["inventory"]
    assert all(entry["status"] == "near_miss" for entry in inventory)
    assert any("cylinder r=10" in entry["description"] for entry in inventory)
    assert any("align predicate values" in step for step in payload["repair"])


def _count_palette_pixels(path: str, rgb: tuple, tolerance: int = 40) -> int:
    """Sampled pixel count near a palette color — highlight visibility check."""

    from PIL import Image

    image = Image.open(path).convert("RGB")
    width, height = image.size
    return sum(
        1
        for x in range(0, width, 3)
        for y in range(0, height, 3)
        if all(
            abs(channel - target) <= tolerance
            for channel, target in zip(image.getpixel((x, y)), rgb)
        )
    )


def test_ql_evidence_highlight_is_visible(tmp_path, monkeypatch):
    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    _RENDER_DEDUP.clear()
    part = _split_band_solid()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.ql.faces().where(scad.ql.surface_type("CYLINDER")).exactly(1).resolve(part)
    evidence = ctx.value.to_dict()["evidence"]
    assert len(evidence) == 1
    rendered = Path(evidence[0]["path"])
    assert rendered.exists()
    assert rendered.stat().st_size > 10_000
    assert evidence[0]["path"] in str(ctx.value)
    # The matched cylinder bands must be ORANGE in the image, not just
    # present in the scene: palette first color #f39c12.
    orange = _count_palette_pixels(str(rendered), (243, 156, 18))
    assert orange > 400, f"highlight not visible: only {orange} sampled orange pixels"


def test_fillet_evidence_highlights_edge_as_line(tmp_path, monkeypatch):
    """The failing edge renders as a crisp orange line, not marker geometry."""

    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    _RENDER_DEDUP.clear()
    box = _box()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.fillet_rsolid(box, [_box_edges(box)[0]], 12)
    evidence = ctx.value.to_dict()["evidence"]
    assert len(evidence) == 1
    orange = _count_palette_pixels(evidence[0]["path"], (243, 156, 18))
    assert orange > 40, f"edge line not visible: only {orange} sampled orange pixels"


def _face_tags(face) -> set:
    try:
        return set(scad.list_tags(shape=face))
    except Exception:
        return set()


def test_ql_highlight_does_not_pollute_user_shape(tmp_path, monkeypatch):
    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    _RENDER_DEDUP.clear()
    part = _split_band_solid()
    tags_before = {tag for face in part._iter_faces() for tag in _face_tags(face)}
    with pytest.raises(scad.SimpleCADError):
        scad.ql.faces().where(scad.ql.surface_type("CYLINDER")).exactly(1).resolve(part)
    tags_after = {tag for face in part._iter_faces() for tag in _face_tags(face)}
    assert tags_before == tags_after
    assert all("diagnostic" not in tag for tag in tags_after)
