"""Bearing standard assemblies built from public SimpleCAD product APIs.

The default factory preserves separate rolling-element components. Callers
that need one solver body for the outer race can request
``fuse_rolling_elements=True``; that mode intentionally embeds the balls into
the outer-race inner wall and records the simplification in metadata.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional

from ..product.assembly import Assembly
from ..product.material import Material
from ..product.part import Part
from ..operators import (
    add_component_rassembly,
    add_connector_rpart,
    add_revolute_constraint_rassembly,
    apply_tag,
    assign_material_rpart,
    chamfer_rsolid,
    ground_component_rassembly,
    identity_placement_rplacement,
    make_assembly_rassembly,
    make_connector_ref_rconnectorref,
    make_face_connector_rconnector,
    make_face_from_wire_rface,
    make_line_redge,
    make_part_rpart,
    make_placement_rplacement,
    make_sphere_rsolid,
    make_three_point_arc_redge,
    make_wire_from_edges_rwire,
    revolve_rsolid,
    set_public_connector_rassembly,
    union_rsolid,
)
from ..core import Face, Solid
from ..topology.tracking import graph_tracking_scope

__all__ = ["build_ball_bearing", "make_ball_bearing_rassembly"]


def _validate_positive_finite(name: str, value: float) -> float:
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    if resolved <= 0.0:
        raise ValueError(f"{name} must be positive")
    return resolved


def _validate_non_negative_finite(name: str, value: float) -> float:
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{name} must be finite")
    if resolved < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return resolved


def _infer_ball_count(ball_pitch_radius: float, ball_diameter: float) -> int:
    circumference = 2.0 * math.pi * ball_pitch_radius
    # A conservative visual default leaves room for a printed cage/gap between
    # adjacent balls instead of packing tangent spheres around the pitch circle.
    return max(3, int(math.floor(circumference / (1.5 * ball_diameter))))


def _validate_ball_count(
    ball_count: Optional[int],
    ball_pitch_radius: float,
    ball_diameter: float,
) -> int:
    if ball_count is None:
        resolved = _infer_ball_count(ball_pitch_radius, ball_diameter)
    else:
        resolved = int(ball_count)
    if resolved < 3:
        raise ValueError("ball_count must be at least 3")

    chord_spacing = 2.0 * ball_pitch_radius * math.sin(math.pi / resolved)
    if chord_spacing <= ball_diameter:
        raise ValueError(
            "ball_count is too high for ball_diameter on the bearing pitch circle"
        )
    return resolved


def _candidate_chamfer_edges(solid: Solid, bearing_width: float) -> List[object]:
    circular_min_length = max(1e-6, bearing_width * 1.1)
    return [edge for edge in solid._iter_edges() if edge.get_length() > circular_min_length]


def _apply_edge_chamfer(solid: Solid, edge_chamfer: float, bearing_width: float) -> Solid:
    if edge_chamfer <= 0.0:
        return solid
    edges = _candidate_chamfer_edges(solid, bearing_width)
    if not edges:
        return solid
    return chamfer_rsolid(solid, edges, edge_chamfer)


def _make_race_ring_solid(
    bore_or_inner_radius: float,
    outer_or_shoulder_radius: float,
    ball_pitch_radius: float,
    groove_radius: float,
    bearing_width: float,
    edge_chamfer: float,
    role: str,
) -> Solid:
    half_width = bearing_width / 2.0
    if role == "inner_ring":
        inner_radius = bore_or_inner_radius
        outer_radius = outer_or_shoulder_radius
        mouth_offset = ball_pitch_radius - outer_radius
        if mouth_offset <= 0.0 or mouth_offset >= groove_radius:
            raise ValueError("inner ring shoulder radius must expose the raceway groove")
        mouth_z = math.sqrt(max(0.0, groove_radius * groove_radius - mouth_offset * mouth_offset))
        points = [
            (inner_radius, 0.0, -half_width),
            (outer_radius, 0.0, -half_width),
            (outer_radius, 0.0, -mouth_z),
            (ball_pitch_radius - groove_radius, 0.0, 0.0),
            (outer_radius, 0.0, mouth_z),
            (outer_radius, 0.0, half_width),
            (inner_radius, 0.0, half_width),
        ]
        arc_start = points[2]
        arc_mid = points[3]
        arc_end = points[4]
        edges = [
            make_line_redge(points[0], points[1]),
            make_line_redge(points[1], arc_start),
            make_three_point_arc_redge(arc_start, arc_mid, arc_end),
            make_line_redge(arc_end, points[5]),
            make_line_redge(points[5], points[6]),
            make_line_redge(points[6], points[0]),
        ]
    elif role == "outer_ring":
        inner_radius = bore_or_inner_radius
        outer_radius = outer_or_shoulder_radius
        mouth_offset = inner_radius - ball_pitch_radius
        if mouth_offset <= 0.0 or mouth_offset >= groove_radius:
            raise ValueError("outer ring shoulder radius must expose the raceway groove")
        mouth_z = math.sqrt(max(0.0, groove_radius * groove_radius - mouth_offset * mouth_offset))
        points = [
            (inner_radius, 0.0, -half_width),
            (outer_radius, 0.0, -half_width),
            (outer_radius, 0.0, half_width),
            (inner_radius, 0.0, half_width),
            (inner_radius, 0.0, mouth_z),
            (ball_pitch_radius + groove_radius, 0.0, 0.0),
            (inner_radius, 0.0, -mouth_z),
        ]
        arc_start = points[4]
        arc_mid = points[5]
        arc_end = points[6]
        edges = [
            make_line_redge(points[0], points[1]),
            make_line_redge(points[1], points[2]),
            make_line_redge(points[2], points[3]),
            make_line_redge(points[3], arc_start),
            make_three_point_arc_redge(arc_start, arc_mid, arc_end),
            make_line_redge(arc_end, points[0]),
        ]
    else:
        raise ValueError("role must be inner_ring or outer_ring")

    profile = make_face_from_wire_rface(
        make_wire_from_edges_rwire(edges),
        normal=(0.0, -1.0, 0.0),
    )
    ring = revolve_rsolid(
        profile,
        axis=(0.0, 0.0, 1.0),
        angle=360.0,
        origin=(0.0, 0.0, 0.0),
    )
    ring = apply_tag(ring, f"role.{role}")
    ring = apply_tag(ring, "group.ball_bearing")
    ring = _apply_edge_chamfer(ring, edge_chamfer, bearing_width)
    ring.set_metadata(
        "std.bearing.ring",
        {
            "role": role,
            "inner_radius": inner_radius,
            "outer_radius": outer_radius,
            "ball_pitch_radius": ball_pitch_radius,
            "groove_radius": groove_radius,
            "raceway_mouth_z": mouth_z,
            "bearing_width": bearing_width,
            "edge_chamfer": edge_chamfer,
        },
    )
    return ring


def _axis_face(solid: Solid, target_z: float) -> Face:
    candidates = []
    for face in solid._iter_faces():
        normal = face.get_normal_at()
        if normal.z < 0.7:
            continue
        center = face.get_center()
        candidates.append((abs(center.z - target_z), -face.get_area(), face))
    if not candidates:
        raise ValueError("no +Z bearing axis face found")
    return min(candidates, key=lambda item: item[0:2])[2]


def _part_with_axis_connector(
    part_id: str,
    body: Solid,
    name: str,
    target_z: float,
) -> Part:
    part = make_part_rpart(part_id, body, name=name)
    axis = make_face_connector_rconnector("axis", _axis_face(body, target_z))
    return add_connector_rpart(part, axis)


def _ball_placement(ball_pitch_radius: float, angle_degrees: float):
    angle = math.radians(angle_degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return make_placement_rplacement(
        origin=(ball_pitch_radius * cos_a, ball_pitch_radius * sin_a, 0.0),
        x_axis=(cos_a, sin_a, 0.0),
        y_axis=(-sin_a, cos_a, 0.0),
    )


@graph_tracking_scope
def make_ball_bearing_rassembly(
    bore_diameter: float,
    outer_diameter: float,
    bearing_width: float,
    ball_diameter: float,
    ball_count: Optional[int] = None,
    raceway_clearance: float = 0.02,
    edge_chamfer: float = 0.0,
    assembly_id: str = "ball_bearing",
    drive_angle_degrees: Optional[float] = None,
    fuse_rolling_elements: bool = False,
    rolling_element_fuse_overlap: float = 0.01,
    material: Optional[Material] = None,
) -> Assembly:
    """Create a parameterized radial ball bearing assembly.

    With ``fuse_rolling_elements=False`` the factory returns separate
    ``outer_ring``, ``inner_ring``, and ``ball_*`` components.  With
    ``fuse_rolling_elements=True`` all rolling elements are translated to
    their authored pitch positions and unioned into the outer-ring body using
    normal boolean mode (``glue=False``).  The fused mode is intended for
    simplified solver or export bodies; it deliberately embeds the balls into
    the outer-race inner wall and therefore does not preserve the nominal
    raceway clearance as a free gap.

    ``material`` is assigned to the generated ring and rolling-element parts.
    """

    bore_diameter_value = _validate_positive_finite("bore_diameter", bore_diameter)
    outer_diameter_value = _validate_positive_finite("outer_diameter", outer_diameter)
    bearing_width_value = _validate_positive_finite("bearing_width", bearing_width)
    ball_diameter_value = _validate_positive_finite("ball_diameter", ball_diameter)
    raceway_clearance_value = _validate_non_negative_finite(
        "raceway_clearance",
        raceway_clearance,
    )
    edge_chamfer_value = _validate_non_negative_finite("edge_chamfer", edge_chamfer)

    if outer_diameter_value <= bore_diameter_value:
        raise ValueError("outer_diameter must be greater than bore_diameter")

    bore_radius = bore_diameter_value / 2.0
    outer_radius = outer_diameter_value / 2.0
    ball_radius = ball_diameter_value / 2.0
    ball_pitch_radius = (bore_radius + outer_radius) / 2.0
    groove_radius = ball_radius + raceway_clearance_value
    inner_groove_root_radius = ball_pitch_radius - groove_radius
    outer_groove_root_radius = ball_pitch_radius + groove_radius
    inner_wall_thickness = inner_groove_root_radius - bore_radius
    outer_wall_thickness = outer_radius - outer_groove_root_radius
    axial_clearance = bearing_width_value / 2.0 - groove_radius

    if inner_wall_thickness <= 0.0 or outer_wall_thickness <= 0.0:
        raise ValueError(
            "ball_diameter plus raceway_clearance leaves no radial wall thickness"
        )
    if axial_clearance <= 0.0:
        raise ValueError(
            "bearing_width must be greater than ball_diameter plus raceway_clearance"
        )

    smallest_feature = min(inner_wall_thickness, outer_wall_thickness, axial_clearance)
    if edge_chamfer_value >= smallest_feature:
        raise ValueError("edge_chamfer must be smaller than the thinnest bearing feature")

    resolved_ball_count = _validate_ball_count(
        ball_count,
        ball_pitch_radius,
        ball_diameter_value,
    )

    outer_ring = _make_race_ring_solid(
        ball_pitch_radius + ball_radius * 0.75,
        outer_radius,
        ball_pitch_radius,
        groove_radius,
        bearing_width_value,
        edge_chamfer_value,
        "outer_ring",
    )
    inner_ring = _make_race_ring_solid(
        bore_radius,
        ball_pitch_radius - ball_radius * 0.75,
        ball_pitch_radius,
        groove_radius,
        bearing_width_value,
        edge_chamfer_value,
        "inner_ring",
    )
    ball = make_sphere_rsolid(radius=ball_radius, center=(0.0, 0.0, 0.0))
    if fuse_rolling_elements:
        if not math.isfinite(rolling_element_fuse_overlap) or rolling_element_fuse_overlap <= 0.0:
            raise ValueError("rolling_element_fuse_overlap must be finite and positive")
        if rolling_element_fuse_overlap >= ball_radius:
            raise ValueError("rolling_element_fuse_overlap must be smaller than ball radius")
    ball = apply_tag(ball, "role.rolling_element")
    ball = apply_tag(ball, "group.ball_bearing")
    ball.set_metadata(
        "std.bearing.ball",
        {
            "diameter": ball_diameter_value,
            "pitch_radius": ball_pitch_radius,
        },
    )

    fused_rolling_ring = outer_ring
    fused_ball_component_ids: List[str] = []
    if fuse_rolling_elements:
        # Move the ball center slightly into the outer race so the union has
        # a positive-volume intersection instead of a tangent-only contact.
        fuse_radius = ball_pitch_radius + ball_radius * 0.75 + rolling_element_fuse_overlap
        fused_balls = [
            make_sphere_rsolid(
                radius=ball_radius,
                center=(
                    fuse_radius * math.cos(2.0 * math.pi * index / resolved_ball_count),
                    fuse_radius * math.sin(2.0 * math.pi * index / resolved_ball_count),
                    0.0,
                ),
            )
            for index in range(resolved_ball_count)
        ]
        fused_rolling_ring = union_rsolid(
            fused_rolling_ring,
            fused_balls,
            glue=False,
            tracking_policy="graph",
        )
        fused_rolling_ring = apply_tag(
            shape=fused_rolling_ring,
            tag="role.rolling_elements_fused_into_outer_ring",
        )

    outer_part = _part_with_axis_connector(
        f"{assembly_id}_outer_ring",
        fused_rolling_ring,
        "Outer bearing ring",
        bearing_width_value / 2.0,
    )
    if material is not None:
        outer_part = assign_material_rpart(part=outer_part, material=material)
    inner_part = _part_with_axis_connector(
        f"{assembly_id}_inner_ring",
        inner_ring,
        "Inner bearing ring",
        bearing_width_value / 2.0,
    )
    if material is not None:
        inner_part = assign_material_rpart(part=inner_part, material=material)
    ball_part = make_part_rpart(f"{assembly_id}_ball", ball, name="Bearing ball")
    if material is not None:
        ball_part = assign_material_rpart(part=ball_part, material=material)

    assembly = make_assembly_rassembly(assembly_id, name="Ball bearing")
    assembly = add_component_rassembly(
        assembly,
        outer_part,
        component_id="outer_ring",
        placement=identity_placement_rplacement(),
    )
    assembly = add_component_rassembly(
        assembly,
        inner_part,
        component_id="inner_ring",
        placement=identity_placement_rplacement(),
    )

    ball_component_ids: List[str] = []
    ball_angles: Dict[str, float] = {}
    if not fuse_rolling_elements:
        digits = max(2, len(str(resolved_ball_count - 1)))
        for index in range(resolved_ball_count):
            component_id = f"ball_{index:0{digits}d}"
            ball_component_ids.append(component_id)
            angle_degrees = 360.0 * index / resolved_ball_count
            ball_angles[component_id] = angle_degrees
            assembly = add_component_rassembly(
                assembly,
                ball_part,
                component_id=component_id,
                placement=_ball_placement(ball_pitch_radius, angle_degrees),
            )

    assembly = add_revolute_constraint_rassembly(
        assembly,
        "inner_outer_revolute",
        make_connector_ref_rconnectorref("outer_ring", "axis"),
        make_connector_ref_rconnectorref("inner_ring", "axis"),
        drive_angle_degrees=drive_angle_degrees,
        name="Inner ring spins in outer ring",
    )
    assembly = set_public_connector_rassembly(
        assembly,
        public_connector_id="outer_axis",
        source_component_id="outer_ring",
        source_connector_id="axis",
        name="Outer ring housing axis",
    )
    assembly = set_public_connector_rassembly(
        assembly,
        public_connector_id="inner_axis",
        source_component_id="inner_ring",
        source_connector_id="axis",
        name="Inner ring shaft axis",
    )
    assembly.set_metadata(
        "std.bearing.ball_bearing",
        {
            "bore_diameter": bore_diameter_value,
            "outer_diameter": outer_diameter_value,
            "bearing_width": bearing_width_value,
            "ball_diameter": ball_diameter_value,
            "ball_count": resolved_ball_count,
            "raceway_clearance": raceway_clearance_value,
            "edge_chamfer": edge_chamfer_value,
            "ball_pitch_radius": ball_pitch_radius,
            "groove_radius": groove_radius,
            "inner_groove_root_radius": inner_groove_root_radius,
            "outer_groove_root_radius": outer_groove_root_radius,
            "inner_wall_thickness": inner_wall_thickness,
            "outer_wall_thickness": outer_wall_thickness,
            "axial_clearance": axial_clearance,
            "outer_component_id": "outer_ring",
            "inner_component_id": "inner_ring",
            "ball_component_ids": ball_component_ids,
            "ball_angles_degrees": ball_angles,
            "rolling_elements_fused": bool(fuse_rolling_elements),
            "rolling_element_fuse_overlap": (
                float(rolling_element_fuse_overlap) if fuse_rolling_elements else None
            ),
            "rolling_element_fuse_mode": (
                "outer_ring_union" if fuse_rolling_elements else "components"
            ),
            "axis_connector_id": "axis",
            "outer_axis_connector_id": "outer_axis",
            "inner_axis_connector_id": "inner_axis",
            "revolute_constraint_id": "inner_outer_revolute",
        },
    )
    return assembly


def build_ball_bearing(
    *,
    bore_diameter: float,
    outer_diameter: float,
    bearing_width: float,
    ball_diameter: float,
    ball_count: Optional[int] = None,
    raceway_clearance: float = 0.02,
    edge_chamfer: float = 0.0,
    assembly_id: str = "std_ball_bearing",
    revision: str = "1.0.0",
    drive_angle_degrees: Optional[float] = None,
    fuse_rolling_elements: bool = True,
    rolling_element_fuse_overlap: float = 0.01,
    material: Optional[Material] = None,
    ground: Optional[str] = "outer_ring",
):
    """Build one ball bearing as a reusable durable sub-assembly definition.

    Returns an ``AssemblyBuildResult`` whose definition re-declares the
    standard library contract: public ``outer_axis``/``inner_axis`` connectors
    over one internal ``inner_outer_revolute`` constraint, returned unsolved so
    a parent assembly can drive both rings through external fixed constraints.
    ``ground`` selects the ring the nested definition grounds for its own
    constraint solve (``"outer_ring"``, ``"inner_ring"``, or ``None``).
    """

    from ..build import assemble, part

    stdlib_root = Path(__file__).resolve().parents[2]

    if ground not in (None, "outer_ring", "inner_ring"):
        raise ValueError("ground must be 'outer_ring', 'inner_ring', or None")
    if material is not None:
        # Each ring is recorded in its own build graph, so the material is
        # passed by value: a copy without the caller's graph lineage (a
        # material made in a notebook cell belongs to the notebook's graph).
        material = Material(
            material.material_id,
            name=material.name,
            density=material.density,
            density_unit=material.density_unit,
            color=material.color,
        )

    def _spec_kwargs():
        return dict(
            bore_diameter=bore_diameter,
            outer_diameter=outer_diameter,
            bearing_width=bearing_width,
            ball_diameter=ball_diameter,
            ball_count=ball_count,
            raceway_clearance=raceway_clearance,
            edge_chamfer=edge_chamfer,
            assembly_id=assembly_id,
            drive_angle_degrees=drive_angle_degrees,
            fuse_rolling_elements=fuse_rolling_elements,
            rolling_element_fuse_overlap=rolling_element_fuse_overlap,
            material=material,
        )

    def _component_result(component_id: str, role: str):
        # The definition id is the part id the factory gives the component:
        # ``<assembly_id>_<role>``; every ball component shares the one
        # ``<assembly_id>_ball`` part.
        @part(
            id=f"{assembly_id}_{role}",
            revision=revision,
            project_root=stdlib_root,
        )
        def build_ring() -> Part:
            return make_ball_bearing_rassembly(**_spec_kwargs()).get_component(
                component_id
            ).item

        return build_ring()

    outer = _component_result("outer_ring", "outer_ring")
    inner = _component_result("inner_ring", "inner_ring")
    declared = (outer, inner)
    if not fuse_rolling_elements:
        ball = _component_result("ball_00", "ball")
        declared = (*declared, ball)

    @assemble(
        id=assembly_id,
        revision=revision,
        definitions=declared,
        project_root=stdlib_root,
    )
    def build() -> Assembly:
        bearing = make_assembly_rassembly(
            assembly_id,
            name=f"{assembly_id} standard ball bearing",
        )
        identity = identity_placement_rplacement()
        bearing = add_component_rassembly(
            bearing,
            outer.part,
            component_id="outer_ring",
            placement=identity,
        )
        bearing = add_component_rassembly(
            bearing,
            inner.part,
            component_id="inner_ring",
            placement=identity,
        )
        if not fuse_rolling_elements:
            # The ball layout of make_ball_bearing_rassembly, computed here:
            # calling the factory would add a second assembly with this id
            # to the build session.
            pitch_radius = (bore_diameter + outer_diameter) / 4.0
            count = _validate_ball_count(ball_count, pitch_radius, ball_diameter)
            digits = max(2, len(str(count - 1)))
            for index in range(count):
                component_id = f"ball_{index:0{digits}d}"
                bearing = add_component_rassembly(
                    bearing,
                    ball.part,
                    component_id=component_id,
                    placement=_ball_placement(pitch_radius, 360.0 * index / count),
                )
                bearing = ground_component_rassembly(bearing, component_id)
        if ground is not None:
            bearing = ground_component_rassembly(bearing, ground)
        bearing = add_revolute_constraint_rassembly(
            bearing,
            "inner_outer_revolute",
            make_connector_ref_rconnectorref("outer_ring", "axis"),
            make_connector_ref_rconnectorref("inner_ring", "axis"),
            drive_angle_degrees=drive_angle_degrees,
            name="Inner ring spins in outer ring",
        )
        bearing = set_public_connector_rassembly(
            bearing,
            public_connector_id="outer_axis",
            source_component_id="outer_ring",
            source_connector_id="axis",
            name="Outer ring housing axis",
        )
        bearing = set_public_connector_rassembly(
            bearing,
            public_connector_id="inner_axis",
            source_component_id="inner_ring",
            source_connector_id="axis",
            name="Inner ring shaft axis",
        )
        return bearing

    return build()
