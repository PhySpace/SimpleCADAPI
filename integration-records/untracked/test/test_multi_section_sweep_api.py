import pytest

import simplecadapi as scad
from simplecadapi.inspect import brep


def _line_wire(start, end):
    return scad.make_wire_from_edges_rwire([scad.make_line_redge(start, end)])


def _straight_sections():
    return [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(12.0, 8.0, center=(0.0, 0.0, 10.0)),
        scad.make_rectangle_rwire(6.0, 4.0, center=(0.0, 0.0, 20.0)),
    ]


def test_multi_section_sweep_builds_solid_and_open_shell():
    path = _line_wire((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))
    sections = _straight_sections()

    solid = scad.multi_section_sweep_rsolid(
        sections,
        path,
        with_correction=True,
        start_face_tag="multi.start",
        end_face_tag="multi.end",
        side_faces_tag="multi.side",
    )
    shell = scad.multi_section_sweep_rshell(
        sections,
        path,
        with_correction=True,
        start_edges_tag="multi_shell.start",
        end_edges_tag="multi_shell.end",
        side_faces_tag="multi_shell.side",
    )

    assert isinstance(solid, scad.Solid)
    assert len(solid._iter_faces()) == 6
    assert isinstance(shell, scad.Shell)
    assert len(shell._iter_faces()) == 4


def test_multi_section_sweep_supports_endpoint_vertex_and_auxiliary_spine():
    path = _line_wire((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))
    auxiliary = _line_wire((10.0, 0.0, 0.0), (10.0, 0.0, 20.0))
    sections = _straight_sections()

    pointed = scad.multi_section_sweep_rsolid(
        [sections[0], sections[1], scad.make_point_rvertex(0.0, 0.0, 20.0)],
        path,
        with_correction=True,
    )
    guided_frame = scad.multi_section_sweep_rsolid(
        sections,
        path,
        frame_policy="auxiliary_spine",
        auxiliary_spine=auxiliary,
        with_correction=True,
    )

    assert isinstance(pointed, scad.Solid)
    assert isinstance(guided_frame, scad.Solid)


def test_multi_section_sweep_rejects_interior_vertex_and_mismatched_policy():
    path = _line_wire((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))
    sections = _straight_sections()
    interior_point = scad.make_point_rvertex(0.0, 0.0, 10.0)

    with pytest.raises(scad.SimpleCADError, match="Vertex sections only"):
        scad.multi_section_sweep_rsolid(
            [sections[0], interior_point, sections[-1]], path
        )
    with pytest.raises(scad.SimpleCADError, match="requires auxiliary_spine"):
        scad.multi_section_sweep_rsolid(
            sections, path, frame_policy="auxiliary_spine"
        )


@pytest.mark.parametrize(
    ("builder_name", "expected_type", "expected_op"),
    [
        (
            "multi_section_sweep_rsolid",
            scad.Solid,
            "make_multi_section_sweep_rsolid",
        ),
        (
            "multi_section_sweep_rshell",
            scad.Shell,
            "make_multi_section_sweep_rshell",
        ),
    ],
)
def test_multi_section_sweep_graph_json_replays(
    builder_name, expected_type, expected_op
):
    with scad.GraphSession() as session:
        path = _line_wire((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))
        result = getattr(scad, builder_name)(
            _straight_sections(), path, with_correction=True
        )

    restored = scad.import_graph_json(scad.export_graph_json(session.graph))
    replayed = scad.replay_graph(restored)

    assert isinstance(result, expected_type)
    assert session.graph.leaf_nodes()[0].op == expected_op
    assert len(replayed) == 1
    assert isinstance(replayed[0], expected_type)


@pytest.mark.parametrize(
    ("builder_name", "filename"),
    [
        ("multi_section_sweep_rsolid", "multi-section-solid.step"),
        ("multi_section_sweep_rshell", "multi-section-shell.step"),
    ],
)
def test_multi_section_sweep_step_roundtrip(builder_name, filename, tmp_path):
    path = _line_wire((0.0, 0.0, 0.0), (0.0, 0.0, 20.0))
    monotonic_sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(10.0, 7.0, center=(0.0, 0.0, 10.0)),
        scad.make_rectangle_rwire(12.0, 8.0, center=(0.0, 0.0, 20.0)),
    ]
    result = getattr(scad, builder_name)(
        monotonic_sections, path, with_correction=True
    )

    report = brep.validate_step_roundtrip_rdescriptor(
        result.wrapped,
        tmp_path / filename,
        compact=True,
    )

    assert report["passed"] is True
    assert report["topology_deltas"]["faces"] == 0
    assert report["topology_deltas"]["edges"] == 0
    assert report["property_deltas"]["relative_surface_area"] < 1.0e-12
