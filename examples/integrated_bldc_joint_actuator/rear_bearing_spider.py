# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "rear_bearing_spider"
# ///
"""Removable four-arm spider that carries the rear motor bearing.

It sits on the motor shell's rear columns and shares their four M2.5 screws,
so it comes off without disturbing the rotor's front bearing.

    sca run examples/integrated_bldc_joint_actuator/rear_bearing_spider.py
"""

import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad

    from common import (
        apply_tags,
        make_annulus_rsolid,
        make_axial_hole_cutters_rsolids,
        make_axis_part_rpart,
        radial_centers,
    )
    from dimensions import (
        REAR_BEARING_CENTER_Z,
        REAR_COLUMN_PCD,
        REAR_FASTENER_HOLE_RADIUS,
        REAR_SPIDER_BOSS_RADIUS,
        REAR_SPIDER_BOTTOM_Z,
    )
    from materials import make_actuator_material_rmaterial


@app.cell
def _():
    # ---- feature: spider-body (build) ----
    # Bearing hub + four radial arms ending in column bosses.
    _solids = [
        make_annulus_rsolid(
            outer_radius=10.5,
            inner_radius=8.05,
            bottom_z=REAR_SPIDER_BOTTOM_Z,
            height=5.0,
            tag_prefix="housing.rear.spider.bearing.hub",
            tags=("role.rear_motor_bearing_seat",),
        )
    ]
    for _index, _angle, _center in radial_centers(count=4, radius=REAR_COLUMN_PCD / 2.0):
        _arm = scad.make_box_rsolid(
            width=12.0,
            height=3.0,
            depth=5.0,
            bottom_face_center=(14.5, 0.0, REAR_SPIDER_BOTTOM_Z),
            tag_prefix=f"housing.rear.spider.arm{_index + 1}",
            result_tag=f"feature.housing.rear.spider.arm{_index + 1}",
        )
        _solids.append(
            scad.rotate_shape(shape=_arm, angle=_angle, axis=(0.0, 0.0, 1.0), origin=(0.0, 0.0, 0.0))
        )
        _solids.append(
            scad.make_cylinder_rsolid(
                radius=REAR_SPIDER_BOSS_RADIUS,
                height=5.0,
                bottom_face_center=(_center[0], _center[1], REAR_SPIDER_BOTTOM_Z),
                axis=(0.0, 0.0, 1.0),
                tag_prefix=f"housing.rear.spider.boss{_index + 1}",
                result_tag=f"feature.housing.rear.spider.boss{_index + 1}",
            )
        )
    spider_body = scad.union_rsolid(_solids, glue=False)
    return (spider_body,)


@app.cell
def _(spider_body):
    # ---- feature: fastener-clearances (subtract) ----
    fastener_clearances = scad.cut_rsolid(
        spider_body,
        make_axial_hole_cutters_rsolids(
            count=4,
            pcd=REAR_COLUMN_PCD,
            hole_radius=REAR_FASTENER_HOLE_RADIUS,
            bottom_z=REAR_SPIDER_BOTTOM_Z - 1.0,
            height=7.0,
            tag_prefix="housing.rear.spider.fastener.clearance",
        ),
        skip_non_intersecting=False,
    )
    return (fastener_clearances,)


@app.cell
def _(fastener_clearances):
    # ---- product: axis connectors ----
    rear_bearing_spider = make_axis_part_rpart(
        part_id=scad.notebook_id(),
        body=apply_tags(
            shape=fastener_clearances,
            tags=("role.removable_rear_bearing_spider", "group.integrated_bldc_actuator"),
        ),
        name="Four-arm removable rear motor-bearing spider",
        material=make_actuator_material_rmaterial(key="carrier"),
        connectors=(
            ("shell_axis", (0.0, 0.0, REAR_SPIDER_BOTTOM_Z), "Motor shell column interface"),
            ("bearing_axis", (0.0, 0.0, REAR_BEARING_CENTER_Z), "Rear motor bearing outer seat"),
        ),
    )
    return (rear_bearing_spider,)


if __name__ == "__main__":
    app.run()
