"""Render the BLDC actuator showcase images from the captured package.

Outputs (examples/integrated_bldc_joint_actuator/out/):
  bldc_assembly.png    assembled actuator, isometric hero view (studio style)
  bldc_front.png       assembled, front view (studio style)
  bldc_exploded.png    exploded view (studio style)

The exploded view separates the actuator into exactly four modules — ESC,
motor, two-stage reducer, output shaft — displaced AXIALLY ONLY along the
assembly axis (every module keeps its in-module pose, with concentric
radius bands peeling apart so the gears stay visible). The exploded hero
still and the GIF are shot from an INCLINED circular camera orbit whose
view-up is the track normal, so the stack leans in frame and the model
genuinely rotates as the camera circles it.

The script captures the product package (``export.capture_package``, unless
``--reuse-package``), re-opens the .scadpkg (which also serves as the package
reopen gate), materializes the definition DAG, and applies each component's
composed placement to its part body before render.

    uv run python examples/integrated_bldc_joint_actuator/render_showcase.py [--reuse-package] [--skip-gif]
"""
from __future__ import annotations

import math
from pathlib import Path

import simplecadapi as scad
from simplecadapi.kernel.ocp_properties import center_of_mass

from export import OUT_DIR, PACKAGE_PATH, capture_package

# Exploded view tuning: module separation along the axis, then a world tilt
# that lays the stack on the frame diagonal so GAP can stay generous while
# the rendered image remains compact. Inside a module, concentric parts
# (ring gear -> planets -> planet bearings, stator -> rotor) peel apart
# axially by radius band, so the gears are actually visible — every part
# still moves along z only.
GROUP_GAP = 40.0         # axial gap between adjacent module bounding boxes, mm
INTRA_GAP = 24.0         # axial stagger between concentric radius bands, mm
RADIUS_BAND_MM = 3.0     # parts within this radial band share one layer
EXPLODE_ZOOM = 5.5       # fit the full tilted stack; higher clips a corner
# The exploded stack is ~550 mm long, so the default studio edge tubes
# (0.0026 x span) are fatter than a planet gear — thin them out here.
EXPLODE_EDGE_SCALE = 0.0011

# Camera rides an INCLINED circular orbit while the stack explodes along its
# own (vertical) axis: the tilted track plus its plane normal as view-up
# makes the model lean in frame and genuinely rotate as the camera circles.
ORBIT_TILT_DEG = 55.0    # track plane tilted this far from horizontal (steep = more model lean)
STILL_ORBIT_PHASE = 45.0  # orbit phase (deg) used for the exploded hero still

# Exploded-view animation: seamless 360° loop — hold assembled, explode out,
# spin the exploded stack, fold back. 15 fps keeps the GIF around 4 MB.
GIF_FRAMES = 72
GIF_FPS = 15
GIF_SIZE = (840, 525)
GIF_ZOOM = 6.5
GIF_EDGE_SCALE = 0.0014
GIF_LINEAR_DEFLECTION = 0.18
GIF_ANGULAR_DEFLECTION = 0.12

# The two housings would hide every gear, so the exploded view drops them
# (the assembled renders keep them). Exact leaf paths.
HOUSINGS_HIDDEN_IN_EXPLODE = ("/motor_shell", "/reducer_housing")

# Module grouping by leaf part path. Assign every leaf exactly once; the
# four clusters move as rigid axial units.
REDUCER_TOKENS = (
    "reducer_housing", "stage1_ring", "stage1_planet", "stage1_planet_bearing",
    "stage1_carrier", "interstage_bearing", "stage2_ring", "stage2_planet",
    "stage2_planet_bearing",
)
MOTOR_TOKENS = (
    "motor_shell", "stator", "rotor", "rear_motor_bearing", "front_motor_bearing",
    "rear_bearing_spider",
)
ESC_TOKENS = ("controller", "rear_electronics_cover")
OUTPUT_TOKENS = ("output_carrier", "output_bearing", "output_bearing_cap")


def _center(solid: scad.Solid):
    return center_of_mass(solid.wrapped)


def _z_rotation(placement: scad.Placement) -> tuple[float, tuple[float, float, float]]:
    """Placement -> (z-rotation degrees, translation). Asserts the frame is a
    pure z-rotation (true for every placement in this coaxial actuator)."""
    x, y, z = placement.x_axis, placement.y_axis, placement.z_axis
    if abs(z[2] - 1.0) > 1e-9 or abs(x[2]) > 1e-9 or abs(y[2]) > 1e-9:
        raise ValueError(f"non-z-rotation placement frame: x={x} y={y} z={z}")
    if (x[0] * y[1] - x[1] * y[0]) < 0:
        raise ValueError(f"left-handed frame: x={x} y={y}")
    angle = math.degrees(math.atan2(x[1], x[0]))
    return angle, placement.origin


def _compose(
    parent: tuple[float, tuple[float, float, float]],
    child: tuple[float, tuple[float, float, float]],
) -> tuple[float, tuple[float, float, float]]:
    p_angle, p_t = parent
    c_angle, c_t = child
    rad = math.radians(p_angle)
    cos, sin = math.cos(rad), math.sin(rad)
    t = (
        cos * c_t[0] - sin * c_t[1] + p_t[0],
        sin * c_t[0] + cos * c_t[1] + p_t[1],
        c_t[2] + p_t[2],
    )
    return p_angle + c_angle, t


def _flatten(
    item, transform: tuple[float, tuple[float, float, float]], out: list, path: str = ""
):
    if isinstance(item, scad.Part):
        out.append((path or item.part_id, item, transform))
        return
    for cid in item.component_ids():
        component = item.get_component(cid)
        child = _z_rotation(component.placement)
        _flatten(component.item, _compose(transform, child), out, f"{path}/{cid}")


def _place(body: scad.Solid, transform: tuple[float, tuple[float, float, float]]) -> scad.Solid:
    angle, t = transform
    shape = body
    if abs(angle) > 1e-9:
        shape = scad.rotate_shape(shape, angle, axis=(0.0, 0.0, 1.0))
    if any(abs(v) > 1e-12 for v in t):
        shape = scad.translate_shape(shape, t)
    return shape


def _axis_radius(solid: scad.Solid) -> float:
    """Max radial extent of the solid from the z axis (bbox x/y extremes)."""
    from simplecadapi.kernel.ocp_properties import bounding_box

    bb = bounding_box(solid.wrapped)
    return max(abs(bb.xmin), abs(bb.xmax), abs(bb.ymin), abs(bb.ymax))


def _group_of(path: str) -> str:
    for group, tokens in (
        ("esc", ESC_TOKENS),
        ("output", OUTPUT_TOKENS),
        ("reducer", REDUCER_TOKENS),
        ("motor", MOTOR_TOKENS),
    ):
        if any(token in path for token in tokens):
            return group
    raise ValueError(f"leaf part not covered by any module group: {path}")


def _inclined_orbit(phase_deg: float, tilt_deg: float = ORBIT_TILT_DEG) -> tuple[float, float, tuple[float, float, float]]:
    """Camera pose on a circular track tilted `tilt_deg` from horizontal.

    Returns (elevation, azimuth, view_up). The view-up is the track plane's
    normal, so the world-z stack leans in frame and the model visibly rotates
    as the phase sweeps a full circle.
    """
    beta = math.radians(tilt_deg)
    phi = math.radians(phase_deg)
    elevation = math.degrees(math.asin(math.sin(beta) * math.sin(phi)))
    azimuth = math.degrees(math.atan2(math.cos(beta) * math.sin(phi), math.cos(phi)))
    return elevation, azimuth, (0.0, -math.sin(beta), math.cos(beta))


def main(*, capture: bool = True, skip_gif: bool = False) -> None:
    if capture:
        capture_package()
    definition = scad.load_product_package(PACKAGE_PATH)
    root = scad.materialize_definition(definition)
    print(f"materialized: {type(root).__name__}")

    leaves: list[tuple[str, scad.Part, tuple]] = []
    _flatten(root, (0.0, (0.0, 0.0, 0.0)), leaves)
    print(f"leaf parts: {len(leaves)}")

    placed = [(name, _place(part.body, tf)) for name, part, tf in leaves]
    centers = [_center(body) for _, body in placed]
    centroid = (
        sum(c.x for c in centers) / len(centers),
        sum(c.y for c in centers) / len(centers),
        sum(c.z for c in centers) / len(centers),
    )
    total_volume = sum(body.get_volume() for _, body in placed)
    print(f"volume={total_volume:.1f} mm^3 centroid={tuple(round(v, 1) for v in centroid)}")

    solids = [body for _, body in placed]
    scad.render_screenshot_rpath(
        shapes=solids, output_path=str(OUT_DIR / "bldc_assembly.png"),
        view=(30.0, 35.0), image_size=(2200, 1400),
        linear_deflection=0.1, angular_deflection=0.06,
        style="studio", show_axes=False, show_callouts=False, show_legend=False)
    scad.render_screenshot_rpath(
        shapes=solids, output_path=str(OUT_DIR / "bldc_front.png"),
        view=(0.0, 0.0), image_size=(2200, 1400),
        linear_deflection=0.1, angular_deflection=0.06,
        style="studio", show_axes=False, show_callouts=False, show_legend=False)

    # Axial-only module explode: each leaf is assigned to exactly one of the
    # four modules; modules separate along z by rank, and inside a module
    # concentric radius bands peel apart axially (outermost band stays,
    # deeper bands step out) so gears and bearings are exposed. Every
    # displacement is along z — no radial motion.
    groups: dict[str, list[int]] = {}
    for i, (name, _) in enumerate(placed):
        if name in HOUSINGS_HIDDEN_IN_EXPLODE:
            continue
        groups.setdefault(_group_of(name), []).append(i)
    if set(groups) != {"esc", "motor", "reducer", "output"}:
        raise ValueError(f"module grouping incomplete: {sorted(groups)}")
    group_z = {
        group: sum(centers[i].z for i in members) / len(members)
        for group, members in groups.items()
    }
    order = sorted(group_z, key=group_z.get)
    print("module order along z:", " -> ".join(f"{g} ({group_z[g]:+.1f})" for g in order))

    radii = [_axis_radius(body) for _, body in placed]

    # Per-module axial fan: concentric radius bands peel apart in steps of
    # INTRA_GAP (outermost band keeps the part's own z, deeper bands step
    # toward +z). Modules are laid out sequentially along z, each reserving
    # its natural center span plus its fan, so no fan crosses a neighbour.
    module_layout = []
    for group in order:
        members = groups[group]
        band_of = {i: math.ceil(radii[i] / RADIUS_BAND_MM) for i in members}
        layer_rank = {
            band: layer
            for layer, band in enumerate(sorted(set(band_of.values()), reverse=True))
        }
        fan = max(layer_rank.values()) * INTRA_GAP if layer_rank else 0.0
        z_min = min(centers[i].z for i in members)
        z_max = max(centers[i].z for i in members)
        module_layout.append((group, members, band_of, layer_rank, z_min, z_max, fan))

    total_span = sum(
        (z_max - z_min) + fan for _, _, _, _, z_min, z_max, fan in module_layout
    ) + GROUP_GAP * (len(module_layout) - 1)
    cursor = -total_span / 2.0
    layout: list[tuple[scad.Solid, float, tuple[float, float, float]]] = []
    for group, members, band_of, layer_rank, z_min, z_max, fan in module_layout:
        group_dz = cursor - z_min
        for i in members:
            name, body = placed[i]
            layout.append((
                body,
                group_dz + layer_rank[band_of[i]] * INTRA_GAP,
                (centers[i].x, centers[i].y, centers[i].z),
            ))
        print(
            f"  {group:<8} {len(members):>2} parts in {len(layer_rank)} layers,"
            f" fan={fan:.0f} mm, base dz={group_dz:+.1f} mm"
        )
        cursor += (z_max - z_min) + fan + GROUP_GAP
    exploded = [
        scad.translate_shape(body, (0.0, 0.0, amount))
        for body, amount, _ in layout
    ]
    elevation, azimuth, view_up = _inclined_orbit(STILL_ORBIT_PHASE)
    scad.render_screenshot_rpath(
        shapes=exploded, output_path=str(OUT_DIR / "bldc_exploded.png"),
        view=(elevation, azimuth), image_size=(2200, 1400), zoom=EXPLODE_ZOOM,
        linear_deflection=0.1, angular_deflection=0.06, edge_width_scale=EXPLODE_EDGE_SCALE,
        view_up=view_up,
        style="studio", show_axes=False, show_callouts=False, show_legend=False)

    if not skip_gif:
        render_exploded_gif(layout)

    names = ["bldc_assembly.png", "bldc_front.png", "bldc_exploded.png"]
    if not skip_gif:
        names.append("bldc_exploded.gif")
    for name in names:
        path = OUT_DIR / name
        print(f"render {path} ({path.stat().st_size / 1e3:.0f} KB)")


def _explode_profile(u: float) -> float:
    """Explode factor over one loop: hold assembled, ease out, hold exploded,
    ease back — the loop seam lands on the fully assembled pose."""
    hold_in, ramp = 0.17, 0.25
    hold_out = 1.0 - ramp

    def smoothstep(x: float) -> float:
        return x * x * (3.0 - 2.0 * x)

    if u < hold_in:
        return 0.0
    if u < hold_in + ramp:
        return smoothstep((u - hold_in) / ramp)
    if u < hold_out:
        return 1.0
    return 1.0 - smoothstep(min((u - hold_out) / ramp, 1.0))


def render_exploded_gif(layout: list[tuple[scad.Solid, float, tuple[float, float, float]]]) -> None:
    from PIL import Image

    frames_dir = OUT_DIR / "bldc_gif_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for frame in range(GIF_FRAMES):
        u = frame / GIF_FRAMES
        t = _explode_profile(u)
        # Full loop on the inclined track: the camera climbs over the top and
        # dips below while the model explodes and folds back — the stack
        # leans with the track and the model genuinely rotates.
        elevation, azimuth, view_up = _inclined_orbit(360.0 * u)
        solids = [
            scad.translate_shape(body, (0.0, 0.0, dz * t))
            for body, dz, _ in layout
        ]
        path = frames_dir / f"frame_{frame:03d}.png"
        scad.render_screenshot_rpath(
            shapes=solids, output_path=str(path),
            view=(elevation, azimuth), image_size=GIF_SIZE, zoom=GIF_ZOOM,
            linear_deflection=GIF_LINEAR_DEFLECTION,
            angular_deflection=GIF_ANGULAR_DEFLECTION,
            edge_width_scale=GIF_EDGE_SCALE,
            view_up=view_up,
            style="studio", show_axes=False, show_callouts=False, show_legend=False)
        paths.append(path)
        if frame % 12 == 0:
            print(
                f"  gif frame {frame}/{GIF_FRAMES} (t={t:.2f},"
                f" elev={elevation:.0f}, azim={azimuth:.0f})"
            )

    # Fixed palette from the fully-exploded mid frame keeps GIF colors stable
    # across the loop (per-frame adaptive palettes flicker).
    images = [Image.open(path).convert("RGB") for path in paths]
    shared_palette = images[len(images) // 2].quantize(colors=128, method=Image.MEDIANCUT)
    quantized = [image.quantize(palette=shared_palette, dither=Image.FLOYDSTEINBERG) for image in images]
    gif_path = OUT_DIR / "bldc_exploded.gif"
    quantized[0].save(
        gif_path, save_all=True, append_images=quantized[1:],
        duration=int(1000 / GIF_FPS), loop=0, optimize=True,
    )
    for path in paths:
        path.unlink()
    frames_dir.rmdir()


if __name__ == "__main__":
    import sys

    main(capture="--reuse-package" not in sys.argv, skip_gif="--skip-gif" in sys.argv)
