import json

import pytest

import simplecadapi as scad


def test_preflight_loft_reports_json_safe_metrics_and_terminal_mode():
    base = scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0))
    middle = scad.make_rectangle_rwire(5.0, 4.0, center=(0.0, 0.0, 5.0))
    tip = scad.make_point_rvertex(0.0, 0.0, 10.0)

    report = scad.preflight_loft([base, middle, tip], ruled=True)

    assert report["valid"] is True
    assert report["can_build_solid"] is True
    assert report["terminal_mode"] == "end_point"
    assert report["metrics"]["estimated_side_face_count"] == 8
    json.dumps(report)


def test_preflight_loft_distinguishes_shell_from_solid_closure():
    first = scad.make_polyline_rwire([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    second = scad.make_polyline_rwire([(0.0, 0.0, 2.0), (1.0, 0.0, 2.0)])

    shell_report = scad.preflight_loft([first, second], result_kind="shell")
    solid_report = scad.preflight_loft([first, second], result_kind="solid")

    assert shell_report["valid"] is True
    assert shell_report["can_build_shell"] is True
    assert solid_report["valid"] is False
    assert solid_report["errors"][0]["code"] == "open_solid_section"
    with pytest.raises(scad.SimpleCADError, match="open_solid_section"):
        scad.loft_rsolid([first, second])


def test_preflight_loft_rejects_unsupported_boundary_conditions_explicitly():
    sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(5.0, 4.0, center=(0.0, 0.0, 5.0)),
    ]

    report = scad.preflight_loft(
        sections,
        boundary_conditions={
            "start": {"type": "draft", "angle_degrees": 15.0},
            "end": "free",
        },
    )

    assert report["valid"] is False
    assert report["errors"][0]["code"] == "boundary_condition_unsupported"
    assert report["errors"][0]["endpoints"] == ["start"]


def test_preflight_loft_flags_non_monotonic_section_order():
    sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(7.0, 5.0, center=(0.0, 0.0, 10.0)),
        scad.make_rectangle_rwire(6.0, 4.0, center=(0.0, 0.0, 4.0)),
    ]

    report = scad.preflight_loft(sections)

    assert any(
        warning["code"] == "non_monotonic_section_order"
        for warning in report["warnings"]
    )


def test_preflight_loft_flags_smooth_interior_scale_extremum():
    sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(12.0, 9.0, center=(0.0, 0.0, 5.0)),
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 10.0)),
    ]

    report = scad.preflight_loft(sections, ruled=False)

    assert any(
        warning["code"] == "smooth_overshoot_risk"
        for warning in report["warnings"]
    )


@pytest.mark.parametrize(
    ("builder_name", "expected_type", "expected_op"),
    [
        ("loft_rsolid", scad.Solid, "make_loft_rsolid"),
        ("loft_rshell", scad.Shell, "make_loft_rshell"),
    ],
)
def test_loft_approximation_controls_record_and_replay(
    builder_name, expected_type, expected_op
):
    with scad.GraphSession() as session:
        sections = [
            scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
            scad.make_rectangle_rwire(10.0, 7.0, center=(0.0, 0.0, 5.0)),
            scad.make_rectangle_rwire(12.0, 8.0, center=(0.0, 0.0, 10.0)),
        ]
        result = getattr(scad, builder_name)(
            sections,
            smoothing=True,
            continuity="C2",
            parametrization="centripetal",
            max_degree=6,
            tolerance=1.0e-7,
        )

    leaf = session.graph.leaf_nodes()[0]
    replayed = scad.replay_graph(
        scad.import_graph_json(scad.export_graph_json(session.graph))
    )

    assert isinstance(result, expected_type)
    assert leaf.op == expected_op
    assert leaf.params["smoothing"] is True
    assert leaf.params["continuity"] == "C2"
    assert leaf.params["parametrization"] == "centripetal"
    assert leaf.params["max_degree"] == 6
    assert len(replayed) == 1
    assert isinstance(replayed[0], expected_type)


def test_loft_approximation_controls_reject_invalid_values():
    sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(12.0, 8.0, center=(0.0, 0.0, 10.0)),
    ]

    with pytest.raises(scad.SimpleCADError, match="continuity must be"):
        scad.loft_rsolid(sections, continuity="C9")
    with pytest.raises(scad.SimpleCADError, match="max_degree must be"):
        scad.loft_rshell(sections, max_degree=1)


def test_smooth_shell_rejects_endpoint_wire_tag_when_kernel_rebuilds_edges():
    sections = [
        scad.make_rectangle_rwire(8.0, 6.0, center=(0.0, 0.0, 0.0)),
        scad.make_rectangle_rwire(10.0, 7.0, center=(0.0, 0.0, 5.0)),
        scad.make_rectangle_rwire(12.0, 8.0, center=(0.0, 0.0, 10.0)),
    ]

    with pytest.raises(scad.SimpleCADError, match="endpoint Wire roles are unavailable"):
        scad.loft_rshell(
            sections,
            smoothing=True,
            continuity="C2",
            parametrization="centripetal",
            max_degree=6,
            start_wire_tag="start",
        )
