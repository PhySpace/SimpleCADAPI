# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "stage1_carrier"
# ///
"""Planet carrier with pins and coaxial drive shaft: a part family, one per stage.

The ``STAGE`` key selects the stage spec (``dimensions.STAGES``) and the
carrier spec (``dimensions.CARRIERS``). A hub plate above the gear plane
carries three arms ending in round pads; a pin with a wider land hangs from
each pad into a planet bore. The central shaft carries the carrier's output
up the power path: to the stage 2 sun (stage 1) or the output flange
(stage 2).

Face connectors sit on the shaft's top face (``carrier_axis`` plus the drive
connector the next element mates to) and on each pin land's top face
(``planet_<i>_axis``). Bearing seats are topology-free placements.

    sca run examples/compact_two_stage_planetary_reducer/carrier.py --id stage2_carrier --set STAGE=stage2
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import AxialFace, add_placement_axis_connector_rpart, apply_tags, make_axis_part_rpart
    from dimensions import CARRIERS, PLANET_COUNT, STAGES
    from materials import make_reducer_material_rmaterial


@app.function
def z_cylinder(radius: float, height: float, center: tuple[float, float], bottom_z: float, tag: str) -> scad.Solid:
    """A +Z cylinder at ``center``; faces and solid tagged with ``tag``."""
    return scad.make_cylinder_rsolid(
        radius=radius,
        height=height,
        bottom_face_center=(center[0], center[1], bottom_z),
        axis=(0.0, 0.0, 1.0),
        tag_prefix=tag,
        result_tag=f"solid.{tag}",
    )


@app.cell
def _():
    # ---- params: stage ----
    STAGE = "stage1"
    return (STAGE,)


@app.cell
def _(STAGE):
    # ---- feature: carrier-body (build) ----
    # Hub, shaft, arms, pads, pins and pin lands fused in one union.
    _stage = STAGES[STAGE]
    _spec = CARRIERS[STAGE]
    _prefix = f"reducer.{STAGE}.carrier"
    _solids = [
        z_cylinder(_spec.hub_radius, _spec.plate_thickness, (0.0, 0.0), _spec.plate_bottom_z, f"{_prefix}.hub"),
        z_cylinder(
            _spec.shaft_radius,
            _spec.shaft_top_z - (_spec.plate_bottom_z - 0.05),
            (0.0, 0.0),
            _spec.plate_bottom_z - 0.05,
            f"{_prefix}.shaft",
        ),
    ]
    # The arms grow well into the hub (not a shallow kiss), so torque runs
    # through material and the arms do not read as separate fork prongs.
    _arm_inner_radius = max(_spec.shaft_radius + 0.25, _spec.hub_radius - 1.25)
    _arm_outer_radius = _stage.planet_center_radius + _spec.pad_radius - 0.25
    _pin_height = _spec.plate_bottom_z + _spec.plate_thickness - _spec.pin_bottom_z
    _land_height = _stage.top_z - _spec.pin_bottom_z
    for _index in range(PLANET_COUNT):
        _i = _index + 1
        _angle = _stage.planet_angle(_index)
        _center = _stage.planet_center(_index)
        _arm = scad.make_box_rsolid(
            width=_arm_outer_radius - _arm_inner_radius,
            height=_spec.arm_width,
            depth=_spec.plate_thickness,
            bottom_face_center=((_arm_inner_radius + _arm_outer_radius) / 2.0, 0.0, _spec.plate_bottom_z),
            tag_prefix=f"{_prefix}.arm.i{_i}",
            result_tag=f"solid.{_prefix}.arm.i{_i}",
        )
        if abs(_angle) > 1.0e-9:
            _arm = scad.rotate_shape(shape=_arm, angle=_angle, axis=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0))
        _solids += [
            _arm,
            z_cylinder(_spec.pad_radius, _spec.plate_thickness, _center, _spec.plate_bottom_z, f"{_prefix}.pad.i{_i}"),
            z_cylinder(_spec.pin_radius, _pin_height, _center, _spec.pin_bottom_z, f"{_prefix}.pin.i{_i}"),
            z_cylinder(_spec.pin_land_radius, _land_height, _center, _spec.pin_bottom_z, f"{_prefix}.pin.land.i{_i}"),
        ]
    carrier_body = scad.union_rsolid(_solids, glue=False)
    return (carrier_body,)


@app.cell
def _(STAGE, carrier_body):
    # ---- product: shaft and pin connectors, bearing seats ----
    _stage = STAGES[STAGE]
    _spec = CARRIERS[STAGE]
    _body = apply_tags(carrier_body, tags=(f"role.{STAGE}.planet_carrier", "group.two_stage_reducer"))
    _faces = [
        AxialFace("carrier_axis", target_z=_spec.shaft_top_z, normal_z=1.0),
        AxialFace(_spec.drive_connector_id, target_z=_spec.shaft_top_z, normal_z=1.0),
    ]
    _faces += [
        AxialFace(f"planet_{_i + 1}_axis", target_z=_stage.top_z, normal_z=1.0, center_xy=_stage.planet_center(_i))
        for _i in range(PLANET_COUNT)
    ]
    _part = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        solid=_body,
        name=f"{_stage.label} carrier with planet pins",
        material=make_reducer_material_rmaterial(key="carrier"),
        faces=_faces,
    )
    _part = add_placement_axis_connector_rpart(
        part=_part,
        connector_id=_spec.shaft_bearing_connector_id,
        origin=(0.0, 0.0, _spec.shaft_bearing_z),
        name=_spec.shaft_bearing_name,
    )
    for _i in range(PLANET_COUNT):
        _part = add_placement_axis_connector_rpart(
            part=_part,
            connector_id=f"planet_{_i + 1}_bearing_axis",
            origin=(*_stage.planet_center(_i), _stage.mid_z),
            name=f"{_stage.label} planet {_i + 1} bearing pin axis",
        )
    carrier = _part
    return (carrier,)


if __name__ == "__main__":
    app.run()
