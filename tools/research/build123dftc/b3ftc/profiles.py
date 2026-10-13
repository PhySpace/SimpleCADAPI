"""Exact profile reconstruction through native sketch/curve APIs.

Planar input curves are transcribed into a local sketch, including rational
B-splines and ellipses. Nonplanar sweep paths remain geometry-tier wires.
No tessellation or final-body boundary reconstruction is used.
"""
from __future__ import annotations
import math
from typing import Any, Mapping, Sequence
from .emit import fmt_literal, fmt_num, fmt_vec


def dot(a, b):
    return sum(float(x) * float(y) for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    length = math.sqrt(dot(a, a))
    if length < 1e-12:
        raise ValueError('degenerate frame axis')
    return tuple(float(x) / length for x in a)


def frame(profile):
    normal = unit(profile.get('normal', (0, 0, 1)))
    u = profile.get('u') or profile.get('x_dir')
    if u is None:
        seed = (0, 1, 0) if abs(normal[0]) > .8 else (1, 0, 0)
        u = unit(cross(seed, normal))
    else:
        u = unit(u)
    v = unit(profile.get('v') or profile.get('y_dir') or cross(normal, u))
    return profile.get('origin', (0, 0, 0)), u, v, normal


def circumcenter(a, b, c):
    determinant = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(determinant) < 1e-15:
        raise ValueError('arc points are collinear')
    squared = [dot(p, p) for p in (a, b, c)]
    return ((squared[0] * (b[1] - c[1]) + squared[1] * (c[1] - a[1]) + squared[2] * (a[1] - b[1])) / determinant,
            (squared[0] * (c[0] - b[0]) + squared[1] * (a[0] - c[0]) + squared[2] * (b[0] - a[0])) / determinant)


def oriented_spline(edge):
    """Align basis poles with traced edge traversal before binding endpoints.

    OCCT adaptor poles retain increasing parameter order even when a wire
    traverses the edge backwards. Swapping only its endpoint refs distorts
    cubic and higher-order curves, so reverse the entire exact basis.
    """
    poles = edge.get('poles') or edge.get('control_points')
    start, end = edge.get('start'), edge.get('end')
    if not poles or start is None or end is None or math.dist(start, end) < 1e-9:
        return edge
    if math.dist(start, poles[-1]) > 1e-7 or math.dist(end, poles[0]) > 1e-7:
        return edge
    changed = dict(edge, poles=list(reversed(poles)))
    if edge.get('weights'):
        changed['weights'] = list(reversed(edge['weights']))
    if edge.get('knots'):
        total = edge['knots'][0] + edge['knots'][-1]
        changed['knots'] = [total - knot for knot in reversed(edge['knots'])]
        if edge.get('multiplicities'):
            changed['multiplicities'] = list(reversed(edge['multiplicities']))
    return changed


class Sketch:
    def __init__(self, name, profile):
        self.name = name
        self.origin, self.u, self.v, self.normal = frame(profile)
        plane_expr = "{'origin': " + fmt_vec(self.origin) + ", 'x_axis': " + fmt_vec(self.u) + ", 'y_axis': " + fmt_vec(self.v) + "}"
        self.lines = [f"    {name} = scad.make_sketch_rsketch(name={name!r}, plane={plane_expr})"]
        self.points = {}
        self.counter = 0
        self.entities = 0
        self.snapshot_entities = []

    def local(self, point):
        delta = [float(x) - float(y) for x, y in zip(point, self.origin)]
        if abs(dot(delta, self.normal)) > 1e-5:
            raise ValueError('nonplanar curve cannot be represented by sketch')
        return dot(delta, self.u), dot(delta, self.v)

    def point(self, coordinates):
        key = tuple(round(x, 9) for x in coordinates)
        if key not in self.points:
            self.counter += 1
            point_id = f'p{self.counter}'
            self.points[key] = point_id
            self.lines.append(f'    {self.name} = scad.add_point_rsketch(sketch={self.name}, point_id={point_id!r}, x={fmt_num(coordinates[0])}, y={fmt_num(coordinates[1])})')
            self.snapshot_entities.append({'id': point_id, 'kind': 'point', 'xy': list(coordinates)})
        return self.points[key]

    def entity(self, edge):
        self.entities += 1
        name = f'e{self.entities}'
        prefix = f'    {self.name} = scad.'
        base = f'sketch={self.name}, entity_id={name!r}'
        kind = edge['kind'].lower()
        if kind == 'line':
            a, b = self.point(self.local(edge['start'])), self.point(self.local(edge['end']))
            self.lines.append(prefix + f'add_line_rsketch({base}, start={a!r}, end={b!r})')
            self.snapshot_entities.append({'id': name, 'kind': 'line', 'start': a, 'end': b})
        elif kind in ('arc', 'arc3') or (kind == 'circle' and edge.get('mid') is not None):
            a, b, c = [self.local(edge[x]) for x in ('start', 'mid', 'end')]
            center = circumcenter(a, b, c)
            angles = [math.atan2(p[1] - center[1], p[0] - center[0]) for p in (a, b, c)]
            if (angles[1] - angles[0]) % (2 * math.pi) > (angles[2] - angles[0]) % (2 * math.pi):
                a, c = c, a
            start, end, center_ref = self.point(a), self.point(c), self.point(center)
            self.lines.append(prefix + f'add_arc_rsketch({base}, start={start!r}, end={end!r}, center={center_ref!r})')
            self.snapshot_entities.append({'id': name, 'kind': 'arc', 'start': start, 'end': end, 'center': center_ref})
        elif kind == 'circle':
            center = self.point(self.local(edge['center']))
            self.lines.append(prefix + f'add_circle_rsketch({base}, center={center!r}, radius={fmt_num(edge["radius"])})')
            self.snapshot_entities.append({'id': name, 'kind': 'circle', 'center': center, 'radius': edge['radius']})
        elif kind == 'ellipse':
            if edge.get('trimmed'):
                raise ValueError('trimmed ellipse requires exact trimmed B-spline data')
            center3 = edge['center']
            x_dir = edge.get('x_dir') or self.u
            y_dir = edge.get('y_dir') or cross(edge.get('normal', self.normal), x_dir)
            major3 = [c + edge['major_radius'] * d for c, d in zip(center3, x_dir)]
            minor3 = [c + edge['minor_radius'] * d for c, d in zip(center3, y_dir)]
            center, major, minor = [self.point(self.local(p)) for p in (center3, major3, minor3)]
            self.lines.append(prefix + f'add_ellipse_rsketch({base}, center={center!r}, major_point={major!r}, minor_point={minor!r})')
            self.snapshot_entities.append({'id': name, 'kind': 'ellipse', 'center': center, 'major_point': major, 'minor_point': minor})
        elif kind in ('bspline', 'bezier'):
            edge = oriented_spline(edge)
            poles = edge.get('poles') or edge.get('control_points')
            if not poles:
                raise ValueError('B-spline poles missing')
            a = self.point(self.local(edge.get('start', poles[0])))
            b = self.point(self.local(edge.get('end', poles[-1])))
            degree = int(edge.get('degree', len(poles) - 1 if kind == 'bezier' else 3))
            knots = edge.get('knots', [0, 1] if kind == 'bezier' else None)
            mults = edge.get('multiplicities', [degree + 1, degree + 1] if kind == 'bezier' else None)
            self.lines.append(prefix + f'add_bspline_rsketch({base}, start={a!r}, end={b!r}, control_points={fmt_literal([self.local(p) for p in poles])}, degree={degree}, knots={fmt_literal(knots)}, multiplicities={fmt_literal(mults)}, weights={fmt_literal(edge.get("weights"))}, periodic={bool(edge.get("periodic", False))!r})')
            self.snapshot_entities.append({'id': name, 'kind': 'bspline', 'start': a, 'end': b,
                'control_points': [self.local(p) for p in poles], 'degree': degree,
                'knots': knots, 'multiplicities': mults, 'weights': edge.get('weights'), 'periodic': edge.get('periodic', False)})
        else:
            raise ValueError(f'unsupported exact curve kind: {kind}')


def _polygon_loops(profile, wires, name, snapshots):
    """Compact native sketch construction for a large set of closed polygons."""
    sketches = [Sketch(f'{name}_loop{i}_sketch', profile) for i in range(len(wires))]
    points = []
    for sketch, wire in zip(sketches, wires):
        edges = wire['edges']
        if any(edge['kind'] != 'line' or math.dist(edge['end'], following['start']) > 1e-7
               for edge, following in zip(edges, edges[1:] + edges[:1])):
            return None
        points.append([sketch.local(edge['start']) for edge in edges])
    if snapshots is not None:
        for sketch, wire in zip(sketches, wires):
            edges = wire['edges']
            for edge in edges:
                sketch.entity(edge)
            snapshots.append({'name': sketch.name, 'entities': sketch.snapshot_entities,
                'closed': True, 'compact': True,
                'plane': {'origin': list(sketch.origin), 'x_axis': list(sketch.u), 'y_axis': list(sketch.v)}})
    origin, u, v, normal = frame(profile)
    plane_expr = "{'origin': " + fmt_vec(origin) + ", 'x_axis': " + fmt_vec(u) + ", 'y_axis': " + fmt_vec(v) + "}"
    data, refs = name + '_polygon_points', name + '_loop_wires'
    lines = [f'    {data} = [', *[f'        {fmt_literal(loop)},' for loop in points], '    ]',
             f'    {refs} = []', f'    for _loop_index, _points in enumerate({data}):',
             f'        _loop_sketch = scad.make_sketch_rsketch(name={name!r} + f"_loop{{_loop_index}}_sketch", plane={plane_expr})',
             '        for _point_index, (_x, _y) in enumerate(_points):',
             '            _loop_sketch = scad.add_point_rsketch(sketch=_loop_sketch, point_id=f"p{_point_index + 1}", x=_x, y=_y)',
             '        for _edge_index in range(len(_points)):',
             '            _loop_sketch = scad.add_line_rsketch(sketch=_loop_sketch, entity_id=f"e{_edge_index + 1}", start=f"p{_edge_index + 1}", end=f"p{(_edge_index + 1) % len(_points) + 1}")',
             f'        {refs}.append(scad.make_wire_from_sketch_rwire(sketch=_loop_sketch, profile=0))']
    output = name + '_face'
    lines.append(f'    {output} = scad.make_face_from_wires_rface(outer_wire={refs}[0], inner_wires={refs}[1:], normal={fmt_vec(normal)})')
    return lines, output


def emit_profile(profile: Mapping[str, Any], name: str, *, as_wire: bool = False, snapshots=None):
    """Return source lines + face/wire expression; outer-first wire ordering."""
    wires = profile.get('wires') or [{'edges': profile.get('edges', [])}]
    if not wires or not wires[0].get('edges'):
        raise ValueError('empty profile')
    if as_wire and len(wires) > 1:
        raise ValueError('a wire section cannot represent multiple disconnected loops')
    if not as_wire and len(wires) > 1 and sum(len(wire.get('edges', [])) for wire in wires) > 256:
        # A many-hole face can exceed libslvs' per-system unknown limit even
        # without constraints. Promote each supplied loop in its own small
        # sketch, then construct the same face from all its exact wires.
        if all(wire.get('edges') and all(edge['kind'] == 'line' for edge in wire['edges']) for wire in wires):
            compact = _polygon_loops(profile, wires, name, snapshots)
            if compact is not None:
                return compact
        lines, refs = [], []
        for index, wire in enumerate(wires):
            loop_lines, ref = emit_profile({**profile, 'wires': [wire]}, f'{name}_loop{index}',
                                           as_wire=True, snapshots=snapshots)
            lines.extend(loop_lines)
            refs.append(ref)
        output = name + '_face'
        lines.append(f'    {output} = scad.make_face_from_wires_rface(outer_wire={refs[0]}, inner_wires=[{", ".join(refs[1:])}], normal={fmt_vec(frame(profile)[3])})')
        return lines, output
    sketch = Sketch(name + '_sketch', profile)
    profile_ids = []
    for wire in wires:
        if not wire.get('edges'):
            raise ValueError('empty inner profile')
        profile_ids.append(f'e{sketch.entities + 1}')
        for edge in wire['edges']:
            sketch.entity(edge)
    if snapshots is not None:
        snapshots.append({'name': sketch.name, 'entities': sketch.snapshot_entities,
                          'closed': wires[0].get('closed', not as_wire),
                          'plane': {'origin': list(sketch.origin), 'x_axis': list(sketch.u), 'y_axis': list(sketch.v)}})
    output = name + ('_wire' if as_wire else '_face')
    api = 'make_wire_from_sketch_rwire' if as_wire else 'make_face_from_sketch_rface'
    outer = '0' if len(wires) == 1 else repr(profile_ids[0])
    holes = '' if len(wires) == 1 else f', inner_profiles={profile_ids[1:]!r}'
    sketch.lines.append(f'    {output} = scad.{api}(sketch={sketch.name}, profile={outer}{holes})')
    return sketch.lines, output


def emit_path(path: Mapping[str, Any], name: str, *, snapshots=None):
    if path.get('normal') is not None and path.get('planar', True):
        return emit_profile(path, name, as_wire=True, snapshots=snapshots)
    lines, edges = [], []
    path_edges = path.get('edges') or [edge for wire in path.get('wires', []) for edge in wire.get('edges', [])]
    for index, edge in enumerate(path_edges):
        ref = f'{name}_edge{index}'
        kind = edge['kind']
        if kind == 'line':
            expression = f'scad.make_line_redge(start={fmt_vec(edge["start"])}, end={fmt_vec(edge["end"])})'
        elif kind in ('arc', 'arc3'):
            expression = f'scad.make_three_point_arc_redge(start={fmt_vec(edge["start"])}, middle={fmt_vec(edge["mid"])}, end={fmt_vec(edge["end"])})'
        elif kind == 'circle':
            expression = f'scad.make_circle_redge(center={fmt_vec(edge["center"])}, radius={fmt_num(edge["radius"])}, normal={fmt_vec(edge.get("normal", (0, 0, 1)))})'
        elif kind in ('bspline', 'bezier'):
            edge = oriented_spline(edge)
            degree = int(edge.get('degree', len(edge['poles']) - 1 if kind == 'bezier' else 3))
            expression = (f'scad.make_spline_redge(control_points={fmt_literal(edge["poles"])}, degree={degree}, '
                f'knots={fmt_literal(edge.get("knots"))}, multiplicities={fmt_literal(edge.get("multiplicities"))}, '
                f'weights={fmt_literal(edge.get("weights"))}, periodic={bool(edge.get("periodic", False))!r})')
        else:
            raise ValueError(f'unsupported nonplanar path curve: {kind}')
        lines.append(f'    {ref} = {expression}')
        edges.append(ref)
    if not edges:
        raise ValueError('empty sweep path')
    output = name + '_wire'
    lines.append(f'    {output} = scad.make_wire_from_edges_rwire(edges=[{", ".join(edges)}])')
    return lines, output
