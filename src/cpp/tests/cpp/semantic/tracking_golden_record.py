"""Records tests/cpp/semantic/tracking_golden.hpp from the reference SDK.

    cd ../SimpleCADAPI && .venv/bin/python \
        src/cpp/tests/cpp/semantic/tracking_golden_record.py \
        > src/cpp/tests/cpp/semantic/tracking_golden.hpp

For each scenario in test_tracking_golden.cpp it runs the Python tracked_*
function and writes what the delta says in a form that does not depend on
kernel ids: event counts, and for every entry / role / section edge the
*centres of mass* of the source and result shapes.  The C++ test builds the same
scenario, summarises its delta the same way and compares line by line.
"""

from __future__ import annotations

import sys

import simplecadapi as scad
from simplecadapi._cpp.occt.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_WIRE
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi.kernel.ocp_booleans import fuse_shapes_with_history, solids_of
from simplecadapi.kernel.ocp_properties import center_of_mass
from simplecadapi.topology.tracking import (
    TrackingPolicy,
    _topo_id,
    track_union_history,
    tracked_box,
    tracked_chamfer,
    tracked_cone,
    tracked_cut,
    tracked_cylinder,
    tracked_extrude,
    tracked_fillet,
    tracked_intersect,
    tracked_loft,
    tracked_mirror,
    tracked_revolve,
    tracked_rotate,
    tracked_shell,
    tracked_sweep,
    tracked_translate,
    tracked_twisted_sweep,
    tracked_union,
    tracking_policy_scope,
)


def index_shapes(shapes):
    found = {}
    for root in shapes:
        for kind in (TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE, TopAbs_SOLID):
            explorer = TopExp_Explorer(root, kind)
            while explorer.More():
                shape = explorer.Current()
                found.setdefault(_topo_id(shape), shape)
                explorer.Next()
        found.setdefault(_topo_id(root), root)
    return found


def centre(index, topo_id):
    shape = index.get(topo_id)
    if shape is None:
        return "?"
    c = center_of_mass(shape)
    return "(%.4f,%.4f,%.4f)" % tuple(round(v, 4) + 0.0 for v in (c.x, c.y, c.z))


def summarise(res, inputs, result_shape):
    delta = res.delta
    index = index_shapes(list(inputs) + [result_shape])
    lines = [
        "counts preserved=%d modified=%d generated=%d deleted=%d section_edges=%d entries=%d roles=%d delta_entries=%d"
        % (len(delta.preserved), len(delta.modified), len(delta.generated), len(delta.deleted),
           len(delta.section_edges), len(delta.entries), len(delta.roles), len(res.delta_entries))
    ]
    body = []
    for e in delta.entries:
        src = e.parent_refs[0]
        body.append("E %s|%s|%s|%s|%s|%s@%s->%s@%s" % (
            e.event.name.lower(), e.origin_role or "-", e.metadata["derivation"],
            e.metadata.get("result_role", "-"), "True" if e.metadata.get("project_source_tags") else "False",
            src.kind.name, centre(index, src.topo_id), e.ref.kind.name, centre(index, e.ref.topo_id)))
    for r in delta.roles:
        parent = "-"
        if r.parent_refs:
            parent = "%s@%s" % (r.parent_refs[0].kind.name, centre(index, r.parent_refs[0].topo_id))
        body.append("R %s|%s|%s|%s@%s|%s" % (
            r.role, r.origin_role or "-", r.metadata["evidence_method"], r.ref.kind.name,
            centre(index, r.ref.topo_id), parent))
    for ref in delta.section_edges:
        body.append("S EDGE@%s" % centre(index, ref.topo_id))
    for topo_id, value in res.delta_entries.items():
        body.append("D %s|%s|ev=%s|or=%s|rr=%s|w=%d" % (
            centre(index, topo_id), value["kind"], ",".join(value.get("events", [])),
            ",".join(value.get("origin_roles", [])), ",".join(value.get("result_roles", [])),
            len(value["witnesses"])))
    return lines + sorted(body)


cases = []


def record(name, res, inputs, result_shape=None):
    shape = result_shape if result_shape is not None else (res.shape if hasattr(res, "shape") else res.solid).wrapped
    cases.append((name, summarise(res, inputs, shape)))


def main():
    box = scad.make_box_rsolid(10, 10, 10)
    box_shape = box.wrapped
    record("box", tracked_box((0, 0, 0), 2.0, 3.0, 4.0), [])
    record("cylinder", tracked_cylinder((0, 0, 0), (0, 0, 1), 2.0, 5.0), [])
    record("cone", tracked_cone((0, 0, 0), (0, 0, 1), 3.0, 1.0, 4.0), [])
    record("cone_point", tracked_cone((0, 0, 0), (0, 0, 1), 3.0, 0.0, 4.0), [])
    record("translate", tracked_translate(box, (5, 0, 0)), [box_shape])
    record("rotate", tracked_rotate(box, 45.0, (0, 0, 1)), [box_shape])
    record("mirror", tracked_mirror(box, (0, 0, 0), (1, 0, 0)), [box_shape])

    rect = scad.make_rectangle_rface(5.0, 3.0)
    record("extrude_rect", tracked_extrude(rect, (0, 0, 1), 10.0), [rect.wrapped])
    circle = scad.make_circle_rface(center=(0, 0, 0), radius=2.0, normal=(0, 0, 1))
    record("extrude_circle", tracked_extrude(circle, (0, 0, 1), 3.0), [circle.wrapped])
    profile = scad.make_rectangle_rface(2.0, 1.0, center=(3, 0, 0))
    record("revolve", tracked_revolve(profile, (0, 1, 0), (0, 0, 0), 180.0), [profile.wrapped])
    record("revolve_full", tracked_revolve(profile, (0, 1, 0), (0, 0, 0), 360.0), [profile.wrapped])

    edges = [box.get_edges(i) for i in range(4)]
    record("fillet4", tracked_fillet(box, edges, 0.5), [box_shape])
    record("chamfer4", tracked_chamfer(box, edges, 0.5), [box_shape])
    record("fillet_all", tracked_fillet(box, [box.get_edges(i) for i in range(12)], 1.0), [box_shape])
    top = max(box._iter_faces(), key=lambda f: center_of_mass(f.wrapped).z)
    record("shell", tracked_shell(box, [top], 1.0), [box_shape])

    first = scad.make_rectangle_rwire(2.0, 2.0)
    last = scad.make_rectangle_rwire(1.0, 1.0, center=(0, 0, 2))
    record("loft", tracked_loft([first, last]), [first.wrapped, last.wrapped])
    record("loft_ruled", tracked_loft([first, last], ruled=True), [first.wrapped, last.wrapped])
    square = scad.make_rectangle_rface(1.0, 1.0)
    path = scad.make_segment_rwire((0, 0, 0), (0, 0, 3))
    record("sweep", tracked_sweep(square, path), [square.wrapped, path.wrapped])
    record("twisted_sweep", tracked_twisted_sweep(
        square, axis=(0, 0, 1), origin=(0, 0, 0), distance=3.0, twist_angle=45.0, guide_radius=0.5), [])

    body = scad.make_box_rsolid(10, 10, 10)
    tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
    inside = scad.make_cylinder_rsolid(1.0, 6.0, bottom_face_center=(0, 0, 2))
    cut = tracked_cut(body, tool)
    record("cut_tangent", cut, [body.wrapped, tool.wrapped])
    cut = tracked_cut(body, inside)
    record("cut_blind_hole", cut, [body.wrapped, inside.wrapped])
    union_tool = scad.make_cylinder_rsolid(4.0, 10.0, bottom_face_center=(3, 3, 0))
    union = tracked_union(body, union_tool, glue=False)
    record("union", union, [body.wrapped, union_tool.wrapped])
    common_tool = scad.make_cylinder_rsolid(6.0, 10.0, bottom_face_center=(3, 3, 0))
    common = tracked_intersect(body, common_tool)
    record("intersect", common, [body.wrapped, common_tool.wrapped])

    row = [scad.make_box_rsolid(1.0, 1.0, 1.0, bottom_face_center=(float(i), 0.0, 0.0)) for i in range(3)]
    for clean in (True, False):
        fused = fuse_shapes_with_history([s.wrapped for s in row], glue=False, tol=1e-7, clean=clean)
        result = scad.Solid(solids_of(fused.shape)[0])
        tracked = track_union_history(row, result, fused.history, fused.section_edges)
        record("union3_clean" if clean else "union3_raw", tracked, [s.wrapped for s in row], result.wrapped)

    with tracking_policy_scope(TrackingPolicy.GRAPH):
        record("graph_extrude", tracked_extrude(rect, (0, 0, 1), 10.0), [rect.wrapped])
        record("graph_translate", tracked_translate(box, (5, 0, 0)), [box_shape])
        record("graph_fillet", tracked_fillet(box, edges, 0.5), [box_shape])
        record("graph_cut", tracked_cut(body, tool), [body.wrapped, tool.wrapped])

    out = sys.stdout
    out.write("// Generated by tracking_golden_record.py from the reference SDK; do not edit.\n")
    out.write("#pragma once\n\nnamespace scad::tracking_golden {\n\n")
    out.write("struct Case {\n  const char* name;\n  const char* text;\n};\n\n")
    out.write("inline constexpr Case kCases[] = {\n")
    for name, lines in cases:
        out.write('    {"%s", R"GOLDEN(%s\n)GOLDEN"},\n' % (name, "\n".join(lines)))
    out.write("};\n\n}  // namespace scad::tracking_golden\n")


main()
