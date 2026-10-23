"""Shell operators against the reference SDK: loft, sew, solid from shell, free boundaries, hole filling."""

import pytest

import simplecadapi._cpp as scad
from ref import golden
from surface_support import REF_PRELUDE, T, circle, close_to, error_detail, line, measure, rectangle, spline

BOX_FACES = None


def box_faces():
    return T_box().faces()


def T_box():
    return scad._testing.box(1.0, 2.0, 3.0)


def test_loft_shells_match_the_reference():
    ref_body = """
lower, upper = circle((0, 0, 0), 2.0), circle((0, 0, 2), 1.0)
squares = [rectangle(2, 2, center=(0, 0, 0)), rectangle(1, 1, center=(0, 0, 3))]
result = {"smooth": measure(scad.loft_rshell([lower, upper])),
          "ruled": measure(scad.loft_rshell([lower, upper], ruled=True)),
          # Three sections: the reference cannot name the endpoint boundaries either.
          "three": error_detail(lambda: scad.loft_rshell([lower, circle((0, 0, 1), 1.6), circle((0, 0, 2), 1.0)])),
          "pointed": measure(scad.loft_rshell([upper, scad.make_point_rvertex(0, 0, 4)])),
          "square": measure(scad.loft_rshell(squares)),
          "wires": len(scad.free_boundaries_rwirelist(scad.loft_rshell([lower, upper]), tolerance=1e-7))}
"""
    lower, upper = circle((0, 0, 0), 2.0), circle((0, 0, 2), 1.0)
    squares = [rectangle(2, 2, (0, 0, 0)), rectangle(1, 1, (0, 0, 3))]
    got = {
        "smooth": measure(scad.loft_rshell([lower, upper])),
        "ruled": measure(scad.loft_rshell([lower, upper], ruled=True)),
        "three": error_detail(lambda: scad.loft_rshell([lower, circle((0, 0, 1), 1.6), circle((0, 0, 2), 1.0)])),
        "pointed": measure(scad.loft_rshell([upper, T.point(0, 0, 4)])),
        "square": measure(scad.loft_rshell(squares)),
        "wires": len(scad.free_boundaries_rwirelist(scad.loft_rshell([lower, upper]), tolerance=1e-7)),
    }
    expected = golden("surface_loft_shell", REF_PRELUDE + ref_body)
    assert close_to(got, expected, rel=1e-6), f"native {got}\nreference {expected}"


def test_loft_names_wires_and_faces():
    shell = scad.loft_rshell(
        [circle((0, 0, 0), 2.0), circle((0, 0, 2), 1.0)],
        tag_prefix="skin", result_tag="part.skin", start_wire_tag="anchor.inlet", end_wire_tag="anchor.outlet",
        side_faces_tag="group.side",
    )
    wires = [shell.get_wires(0), shell.get_wires(1)]
    assert sorted(t for w in wires for t in w._list_tags() if t.startswith("anchor.")) == ["anchor.inlet", "anchor.outlet"]
    assert "group.side" in shell.get_faces(0)._list_tags()
    assert {"part.skin", "skin.shell"} <= set(shell._list_tags())
    pointed = scad.loft_rshell([circle((0, 0, 2), 1.0), T.point(0, 0, 4)], start_wire_tag="anchor.base")
    assert "anchor.base" in pointed.get_wires(0)._list_tags()


def test_loft_error_contract():
    lower = circle((0, 0, 0), 2.0)
    for call, needle in (
        (lambda: scad.loft_rshell([lower, T.point(0, 0, 2), circle((0, 0, 4), 1.0)]), "only at the start or end"),
        (lambda: scad.loft_rshell([lower, T.point(0, 0, 2)], end_wire_tag="anchor.end"), "end_wire_tag requires"),
        (lambda: scad.loft_rshell([lower]), "at least two sections"),
    ):
        with pytest.raises(scad.SimpleCADError) as info:
            call()
        assert needle in str(info.value)
        assert info.value.operation == "loft_rshell"


def test_sew_solidify_and_free_boundaries_match_the_reference():
    ref_body = """
box = scad.make_box_rsolid(1.0, 2.0, 3.0)
shell = scad.sew_faces_rshell(box._iter_faces())
solid = scad.make_solid_from_shell_rsolid(shell, tag_prefix="body")
open_face = scad.make_bezier_surface_rface([[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]])
open_shell = scad.sew_faces_rshell([open_face])
boundaries = scad.free_boundaries_rwirelist(open_shell)
result = {"shell": measure(shell), "closed": shell.is_closed(), "solid": measure(solid),
          "free_of_box": len(scad.free_boundaries_rwirelist(shell)),
          "free_of_open": [sum(e.get_length() for e in w._iter_edges()) for w in boundaries]}
"""
    box = scad._testing.box(1.0, 2.0, 3.0)
    shell = scad.sew_faces_rshell(box.faces())
    solid = scad.make_solid_from_shell_rsolid(shell, tag_prefix="body")
    open_shell = scad.sew_faces_rshell([scad.make_bezier_surface_rface([[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]])])
    got = {
        "shell": measure(shell), "closed": shell.is_closed(), "solid": measure(solid),
        "free_of_box": len(scad.free_boundaries_rwirelist(shell)),
        "free_of_open": [sum(e.get_length() for e in w.edges()) for w in scad.free_boundaries_rwirelist(open_shell)],
    }
    expected = golden("surface_sew_solid_boundaries", REF_PRELUDE + ref_body)
    for part in (got, expected):  # the reference box is centred on its base, the raw test box is not
        for key in ("shell", "solid"):
            part[key].pop("bbox")
    assert close_to(got, expected, rel=1e-6), f"native {got}\nreference {expected}"
    assert "body.solid" in solid._list_tags()


def test_fill_holes_closes_a_tube_like_the_reference():
    ref_body = """
tube = scad.loft_rshell([circle((0, 0, 0), 1.0), circle((0, 0, 2), 1.0)])
closed = scad.fill_holes_rshell(tube)
one = scad.fill_holes_rshell(tube, [0])
result = {"closed": measure(closed), "is_closed": closed.is_closed(), "one": measure(one),
          "solid_error": error_detail(lambda: scad.make_solid_from_shell_rsolid(closed)),
          "remaining": len(scad.free_boundaries_rwirelist(one))}
"""
    tube = scad.loft_rshell([circle((0, 0, 0), 1.0), circle((0, 0, 2), 1.0)])
    closed = scad.fill_holes_rshell(tube)
    one = scad.fill_holes_rshell(tube, [0])
    got = {"closed": measure(closed), "is_closed": closed.is_closed(), "one": measure(one),
           "solid_error": error_detail(lambda: scad.make_solid_from_shell_rsolid(closed)),
           "remaining": len(scad.free_boundaries_rwirelist(one))}
    expected = golden("surface_fill_holes", REF_PRELUDE + ref_body)
    assert close_to(got, expected, rel=1e-5), f"native {got}\nreference {expected}"
    with pytest.raises(scad.SimpleCADError, match="list index out of range"):
        scad.fill_holes_rshell(tube, [9])


def test_shared_edge_gordon_patches_sew_into_a_closed_solid():
    # The reference's headline surface test (tests/test_surface_api.py): six wavy patches on a cube.
    import math

    side, amplitude, samples = 40.0, 10.0, 9

    def wave(u, v):
        return amplitude * math.sin(math.pi * u) ** 2 * math.sin(math.pi * v) ** 2 * math.sin(4 * math.pi * u) * math.sin(6 * math.pi * v)

    def corner(label):
        return tuple((1 if c == "+" else -1) * side for c in label)

    def point_on(face, u, v):
        a, b, o = (u - 0.5) * 2 * side, (v - 0.5) * 2 * side, wave(u, v)
        return {"+z": (a, b, side + o), "-z": (a, b, -side - o), "+x": (side + o, a, b), "-x": (-side - o, a, b),
                "+y": (a, side + o, b), "-y": (a, -side - o, b)}[face]

    loops = {"+z": ("--+", "+-+", "+++", "-++"), "-z": ("---", "+--", "++-", "-+-"), "+x": ("+--", "++-", "+++", "+-+"),
             "-x": ("---", "-+-", "-++", "--+"), "+y": ("-+-", "++-", "+++", "-++"), "-y": ("---", "+--", "+-+", "--+")}
    shared = {}
    for corners in loops.values():
        for first, second in zip(corners, corners[1:] + corners[:1]):
            key = tuple(sorted((first, second)))
            shared.setdefault(key, line(corner(key[0]), corner(key[1])))
    faces = []
    for face, c in loops.items():
        profiles = [shared[tuple(sorted((c[0], c[1])))] if r == 0 else shared[tuple(sorted((c[3], c[2])))] if r == samples - 1
                    else spline([point_on(face, k / (samples - 1), r / (samples - 1)) for k in range(samples)]) for r in range(samples)]
        guides = [shared[tuple(sorted((c[0], c[3])))] if k == 0 else shared[tuple(sorted((c[1], c[2])))] if k == samples - 1
                  else spline([point_on(face, k / (samples - 1), r / (samples - 1)) for r in range(samples)]) for k in range(samples)]
        patch = scad.make_gordon_surface_rface(profiles, guides, tolerance=1e-4)
        assert patch.get_area() == pytest.approx(6882.5098716924, rel=1e-4)  # the reference's value
        faces.append(patch)
    shell = scad.sew_faces_rshell(faces=faces, tolerance=1e-5)
    assert shell.is_closed() and len(shell.faces()) == 6
    assert scad.make_solid_from_shell_rsolid(shell).get_volume() == pytest.approx(80.0**3, abs=0.1)
