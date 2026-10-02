# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "four_bar_linkage"
# ///
"""Planar four-bar linkage with a closed kinematic loop.

Four forged links, members of the ``link_bar.py`` family, are joined by
hex-head pivot bolts. The ground span is grounded; crank and rocker pivot on
it and the coupler closes the loop between their tips. The closing revolute
carries an angle limit so the solver can resolve the loop; MJCF export emits
it as a MuJoCo equality.

Bolts are fasteners, not kinematic bodies: each bolt is fixed to one adjacent
bar at its pivot so it shares that bar's rigid group, and the pin fits both
bores because all bar bores share the pivot axis at the assembled pose.

    sca run examples/four_bar_linkage/four_bar_linkage.py
    uv run python examples/four_bar_linkage/export.py       # package + STEP
    uv run python examples/four_bar_linkage/export_mjcf.py  # MuJoCo
"""

import marimo

app = marimo.App()

with app.setup:
    import math

    import simplecadapi as scad

    from dimensions import (
        CLOSURE_ANGLE_LIMIT,
        COUPLER_ASSEMBLED_ANGLE_DEG,
        COUPLER_LENGTH,
        CRANK_ASSEMBLED_ANGLE_DEG,
        CRANK_LENGTH,
        CRANK_PIVOT,
        CRANK_TIP,
        GROUND_LENGTH,
        ROCKER_ASSEMBLED_ANGLE_DEG,
        ROCKER_LENGTH,
        ROCKER_PIVOT,
    )


@app.function
def bar_placement(origin: tuple[float, float], angle_deg: float) -> scad.Placement:
    """Put a bar's ``pivot_a`` at *origin*, the bar turned *angle_deg* CCW.

    The rotation turns the bar frame about the pivot itself; the translation
    to the pivot is not rotated.
    """
    radians = math.radians(angle_deg)
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    return scad.make_placement_rplacement(
        origin=(origin[0], origin[1], 0.0),
        x_axis=(cos_a, sin_a, 0.0),
        y_axis=(-sin_a, cos_a, 0.0),
    )


@app.cell
def _():
    ground_span = scad.use("link_bar.py", id="ground_span", CENTER_DISTANCE=GROUND_LENGTH)
    crank = scad.use("link_bar.py", id="crank", CENTER_DISTANCE=CRANK_LENGTH)
    coupler = scad.use("link_bar.py", id="coupler", CENTER_DISTANCE=COUPLER_LENGTH)
    rocker = scad.use("link_bar.py", id="rocker", CENTER_DISTANCE=ROCKER_LENGTH)
    pivot_bolt = scad.use("pivot_bolt.py")
    return coupler, crank, ground_span, pivot_bolt, rocker


@app.cell
def _(coupler, crank, ground_span, rocker):
    # The bars start at the authored closed pose: crank along +X, coupler
    # and rocker meeting at the two-circle intersection (dimensions.py).
    _assembly = scad.make_assembly_rassembly(
        assembly_id="four_bar_linkage",
        name="Planar four-bar linkage with closed loop",
    )
    for _component_id, _item, _placement in (
        ("ground", ground_span, scad.identity_placement_rplacement()),
        ("crank", crank, bar_placement(CRANK_PIVOT, CRANK_ASSEMBLED_ANGLE_DEG)),
        ("rocker", rocker, bar_placement(ROCKER_PIVOT, ROCKER_ASSEMBLED_ANGLE_DEG)),
        ("coupler", coupler, bar_placement(CRANK_TIP, COUPLER_ASSEMBLED_ANGLE_DEG)),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=_item,
            component_id=_component_id,
            placement=_placement,
            name=_component_id.title(),
        )
    linkage_bars = _assembly
    return (linkage_bars,)


@app.cell
def _(linkage_bars, pivot_bolt):
    # One bolt per joint, at the pivot on the bar's +Z face, fixed to one
    # adjacent bar.
    _rocker_tip = bar_placement(ROCKER_PIVOT, ROCKER_ASSEMBLED_ANGLE_DEG)
    _rocker_tip_xy = (
        _rocker_tip.origin[0] + ROCKER_LENGTH * _rocker_tip.x_axis[0],
        _rocker_tip.origin[1] + ROCKER_LENGTH * _rocker_tip.x_axis[1],
    )
    _assembly = linkage_bars
    for _bolt_id, _host_id, _host_connector, _xy in (
        ("bolt_a", "ground", "pivot_a", CRANK_PIVOT),
        ("bolt_d", "ground", "pivot_b", ROCKER_PIVOT),
        ("bolt_b", "crank", "pivot_b", CRANK_TIP),
        ("bolt_c", "rocker", "pivot_b", _rocker_tip_xy),
    ):
        _assembly = scad.add_component_rassembly(
            assembly=_assembly,
            item=pivot_bolt,
            component_id=_bolt_id,
            placement=scad.make_placement_rplacement(origin=(_xy[0], _xy[1], 0.0)),
            name=_bolt_id.replace("_", " ").title(),
        )
        _assembly = scad.add_fixed_constraint_rassembly(
            assembly=_assembly,
            constraint_id=f"{_bolt_id}_pin",
            connector_a=scad.make_connector_ref_rconnectorref(_host_id, _host_connector),
            connector_b=scad.make_connector_ref_rconnectorref(_bolt_id, "axis"),
        )
    linkage_bolts = _assembly
    return (linkage_bolts,)


@app.cell
def _(linkage_bolts):
    # Drive angles stay None: the authored closed pose is the reference, and
    # a drive would turn a bar to a zero-relative-frame pose that conflicts
    # with the loop closure.
    def _ref(component_id: str, connector_id: str) -> scad.ConnectorRef:
        return scad.make_connector_ref_rconnectorref(component_id, connector_id)

    _assembly = scad.ground_component_rassembly(assembly=linkage_bolts, component_id="ground")
    for _constraint_id, _a, _b in (
        ("crank_to_ground", _ref("ground", "pivot_a"), _ref("crank", "pivot_a")),
        ("rocker_to_ground", _ref("ground", "pivot_b"), _ref("rocker", "pivot_a")),
        ("coupler_to_crank", _ref("crank", "pivot_b"), _ref("coupler", "pivot_a")),
    ):
        _assembly = scad.add_revolute_constraint_rassembly(
            assembly=_assembly, constraint_id=_constraint_id, connector_a=_a, connector_b=_b
        )
    # The loop-closing joint: its limit bounds the solver's search.
    linkage_joints = scad.add_revolute_constraint_rassembly(
        assembly=_assembly,
        constraint_id="coupler_to_rocker",
        connector_a=_ref("rocker", "pivot_b"),
        connector_b=_ref("coupler", "pivot_b"),
        angle_limit=scad.make_scalar_limit_rscalarlimit(
            lower_value=CLOSURE_ANGLE_LIMIT[0], upper_value=CLOSURE_ANGLE_LIMIT[1]
        ),
    )
    return (linkage_joints,)


@app.cell
def _(linkage_joints):
    _assembly = scad.set_public_connector_rassembly(
        assembly=linkage_joints,
        public_connector_id="crank_input_axis",
        source_component_id="crank",
        source_connector_id="pivot_a",
        name="Crank input axis",
    )
    four_bar_linkage = scad.solve_assembly_constraints_rassembly(assembly=_assembly, strict=True)
    return (four_bar_linkage,)


if __name__ == "__main__":
    app.run()
