"""Named primitives shared by the sleeve and piston-rod notebooks."""

import simplecadapi as scad


def named_box(
    *,
    width: float,
    height: float,
    depth: float,
    bottom_face_center: tuple[float, float, float],
    bottom_face_tag: str,
    top_face_tag: str,
    side_faces_tag: str,
    tag_prefix: str,
    result_tag: str,
) -> scad.Solid:
    """A +Z box with its bottom, top and side faces tagged.

    ``make_box_rsolid`` does not name its faces, so the box is a tagged
    rectangle extruded by *depth*.
    """
    profile = scad.make_rectangle_rface(
        # Rectangle profile axes are Y/X for a +Z normal; swap the dimensions
        # to keep make_box_rsolid's global X/Y layout.
        width=height,
        height=width,
        center=bottom_face_center,
        tag_prefix=f"{tag_prefix}.profile",
        edge_tags=("bottom", "right", "top", "left"),
    )
    return scad.extrude_rsolid(
        profile=profile,
        direction=(0.0, 0.0, 1.0),
        distance=depth,
        tag_prefix=tag_prefix,
        result_tag=result_tag,
        start_face_tag=bottom_face_tag,
        end_face_tag=top_face_tag,
        side_faces_tag=side_faces_tag,
    )
