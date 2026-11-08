"""Surfaces from curves (edges) and a closed body from surfaces: the chain the editor offers on picked curves and
surfaces (ruled, loft, Gordon, patch; sew faces and shells; a solid from the closed shell)."""

import pytest

import simplecadapi as s
from simplecadapi.recording.graph import GraphSession


def test_a_closed_body_from_curves_through_surfaces_and_sewing():
    with GraphSession() as session:
        # the four lower and four upper edges of a 10 x 10 x 10 box, as curves
        p = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
        lower = [s.make_segment_redge(p[i], p[(i + 1) % 4]) for i in range(4)]
        upper = [s.make_segment_redge((*p[i][:2], 10), (*p[(i + 1) % 4][:2], 10)) for i in range(4)]
        walls = s.loft_rshell([s.make_wire_from_edges_rwire(lower), s.make_wire_from_edges_rwire(upper)], ruled=True)
        floor = s.make_gordon_surface_rface([lower[0], lower[2]], [lower[1], lower[3]])
        roof = s.make_surface_patch_rface([s.SurfaceBoundary(edge) for edge in upper])
        skin = s.sew_faces_rshell([walls, floor, roof])  # a shell and two faces
        assert skin.is_closed()
        body = s.make_solid_from_shell_rsolid(skin)
        session.capture_result(value=body)
    assert body.get_volume() == pytest.approx(1000.0, rel=1e-3)
    replayed = s.replay_model_json(s.export_model_json(session))[0]
    assert replayed.get_volume() == pytest.approx(body.get_volume())


def test_sewing_takes_faces_and_shells_and_nothing_else():
    a = s.make_segment_redge((0, 0, 0), (10, 0, 0))
    ruled = s.make_ruled_surface_rface(a, s.make_segment_redge((0, 10, 2), (10, 10, 0)))
    assert len(s.ql.faces().resolve(s.sew_faces_rshell([s.sew_faces_rshell([ruled])]))) == 1
    with pytest.raises(s.SimpleCADError, match="takes Face and Shell"):
        s.sew_faces_rshell([a])


def test_the_preview_shows_the_surfaces_no_later_cell_builds_on():
    from simplecadapi.runtime.live import open_surfaces
    from simplecadapi.scene.preview import SURFACE_NODE_PREFIX, PreviewScene, add_surfaces, decode_preview_header, encode_preview

    a = s.make_segment_redge((0, 0, 0), (10, 0, 0))
    b = s.make_interpolated_spline_redge(points=[(0, 0, 10), (5, 4, 12), (10, 0, 15)])
    values = {"a": a, "skin": s.loft_rshell([a, b]), "ruled": s.make_ruled_surface_rface(a, b), "_private": s.make_ruled_surface_rface(a, b)}
    surfaces = open_surfaces(values, read={"ruled"})  # a later cell builds on `ruled`
    assert list(surfaces) == ["skin"]
    scene = add_surfaces(PreviewScene(parts={}, nodes=[], solids={}, definitions={}), surfaces)
    header = decode_preview_header(encode_preview(scene))
    assert [node["node_id"] for node in header["nodes"]] == [SURFACE_NODE_PREFIX + "skin"]
