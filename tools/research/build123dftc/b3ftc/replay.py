"""Translate a portable build123d operation trace into explicit FTC dataflow.

Only recorded feature inputs are reconstructed. Unknown operations block their
own dependent chain instead of being replaced by final-result geometry.
"""
from __future__ import annotations
import math
import re
from typing import Any, Mapping
from .emit import SlugAllocator, block_header, emit_module, fingerprint_selector, fmt_literal, fmt_num, fmt_vec
from .profiles import cross, dot, emit_path, emit_profile, frame, unit


def _named(parameters, *names, default=None):
    for name in names:
        if name in parameters and parameters[name] is not None:
            return parameters[name]
    return default


def _variable(name):
    return 'body_' + re.sub('[^a-zA-Z0-9_]', '_', str(name))


def _axis(parameters):
    value = parameters.get('axis', (0, 0, 1))
    if isinstance(value, dict):
        return value.get('direction', (0, 0, 1)), value.get('origin', (0, 0, 0))
    return value, parameters.get('origin', (0, 0, 0))


def _profiles(step):
    profiles = step.get('profiles') or [step.get('profile')]
    holes = step.get('inner_wires') or []
    if holes and len(profiles) == 1 and profiles[0]:
        profile = dict(profiles[0])
        wires = list(profile.get('wires', []))
        for hole in holes:
            wires.extend(hole.get('wires', [hole]) if isinstance(hole, dict) else [])
        profile['wires'] = wires
        profiles = [profile]
    return profiles


def _matrix_operations(matrix):
    """Decompose an affine matrix into local scale, rotation, translation."""
    if isinstance(matrix, dict):
        matrix = matrix.get('matrix')
    if len(matrix) == 16 and not isinstance(matrix[0], (list, tuple)):
        matrix = [matrix[i:i + 4] for i in range(0, 16, 4)]
    columns = [tuple(float(matrix[i][j]) for i in range(3)) for j in range(3)]
    scales = [math.sqrt(dot(c, c)) for c in columns]
    if min(scales) < 1e-12:
        raise ValueError('singular affine transform')
    axes = [tuple(x / scale for x in column) for column, scale in zip(columns, scales)]
    if any(abs(dot(axes[i], axes[j])) > 1e-8 for i in range(3) for j in range(i + 1, 3)):
        raise ValueError('affine shear cannot be represented by native scale/rotation')
    if dot(cross(axes[0], axes[1]), axes[2]) < 0:
        scales[0] = -scales[0]
        axes[0] = tuple(-x for x in axes[0])
    r = [[axes[j][i] for j in range(3)] for i in range(3)]
    cosine = max(-1., min(1., (r[0][0] + r[1][1] + r[2][2] - 1) / 2))
    angle = math.acos(cosine)
    if angle < 1e-9:
        axis = (0, 0, 1)
    elif abs(angle - math.pi) < 1e-7:
        diagonal = [max(0., (r[i][i] + 1) / 2) for i in range(3)]
        pivot = max(range(3), key=lambda i: diagonal[i])
        axis_list = [0., 0., 0.]
        axis_list[pivot] = math.sqrt(diagonal[pivot])
        for j in range(3):
            if j != pivot:
                axis_list[j] = (r[pivot][j] + r[j][pivot]) / (4 * axis_list[pivot])
        axis = unit(axis_list)
    else:
        axis = unit((r[2][1] - r[1][2], r[0][2] - r[2][0], r[1][0] - r[0][1]))
    return scales, axis, math.degrees(angle), tuple(float(matrix[i][3]) for i in range(3))


class TraceReplayer:
    def __init__(self, trace: Mapping[str, Any], stem: str, constraints_mode: bool = False):
        self.trace = trace
        self.stem = stem
        self.lines = []
        self.variables = {}
        self.steps = {}
        self.unsupported = list(trace.get('unsupported', []))
        self.slugs = SlugAllocator()
        self.feature_count = 0
        self.uses_ql = False
        self.snapshots = []
        self.constraints_mode = constraints_mode
        self.constraint_reports = []

    def profile(self, profile, name, as_wire=False):
        if profile.get('kind') == 'vertex':
            if not as_wire:
                raise ValueError('vertex cannot be a solid profile')
            output = name + '_vertex'
            self.lines.append(f'    {output} = scad.make_point_rvertex({", ".join(f"{axis}={fmt_num(x)}" for axis, x in zip("xyz", profile["point"]))})')
            return output
        lines, expression = emit_profile(profile, name, as_wire=as_wire, snapshots=self.snapshots)
        self.lines.extend(lines)
        return expression

    def source(self, step):
        ids = step.get('inputs', [])
        if isinstance(ids, str):
            ids = [ids]
        missing = [ref for ref in ids if ref not in self.variables]
        if missing:
            raise ValueError(f'input feature unavailable: {missing}')
        return [self.variables[ref] for ref in ids]

    def build_step(self, step):
        op = step['op'].lower()
        p = step.get('parameters') or step.get('params') or {}
        ident = step.get('id', f's{self.feature_count + 1}')
        var = _variable(ident)
        inputs = self.source(step)
        create = op in {'box', 'cylinder', 'cone', 'sphere', 'torus', 'extrude', 'revolve', 'loft', 'sweep', 'sew_solid', 'extrude_linear', 'extrude_linear_with_rotation', 'extrude_taper', 'extrude_twist', 'extrude_until', 'sweep_multi'}
        role = 'build' if create else {'union': 'add', 'fuse': 'add', 'cut': 'subtract', 'intersect': 'intersect', 'compound': 'pattern'}.get(op, 'modify')
        tiers = ['profile=geometry'] if op in {'extrude', 'revolve', 'loft', 'sweep', 'sew_solid', 'extrude_linear', 'extrude_linear_with_rotation', 'torus', 'extrude_taper', 'extrude_twist', 'extrude_until', 'sweep_multi'} else []
        if op in {'sweep', 'sweep_multi'}:
            tiers.append('path=geometry')
        self.lines.append(block_header(self.slugs.allocate(op), role, tiers))
        if op in {'box', 'cylinder', 'cone', 'sphere', 'torus'}:
            self.primitive(op, p, var)
        elif op in {'extrude', 'extrude_linear'}:
            profiles = _profiles(step)
            if not all(profiles):
                raise ValueError('extrusion profile missing')
            direction = _named(p, 'direction', 'vector', 'dir', default=(0, 0, 1))
            distance = _named(p, 'distance', 'amount', 'height')
            if distance is None:
                distance = math.sqrt(dot(direction, direction))
            if distance < 0:
                direction = [-float(x) for x in direction]
                distance = -distance
            refs = [self.profile(profile, f'{var}_profile{i}') for i, profile in enumerate(profiles)]
            self.lines.append(f'    {var} = [scad.extrude_rsolid(profile=_profile, direction={fmt_vec(direction)}, distance={fmt_num(distance)}) for _profile in [{", ".join(refs)}]]')
        elif op in {'extrude_taper', 'extrude_until', 'extrude_twist', 'extrude_linear_with_rotation'}:
            refs = [self.profile(profile, f'{var}_profile{i}') for i, profile in enumerate(_profiles(step))]
            if op == 'extrude_taper':
                vector = _named(p, 'direction', 'vector', default=(0, 0, 1))
                expression = f'scad.extrude_taper_rsolid(profile=_profile, vector={fmt_vec(vector)}, taper={fmt_num(p["taper"])}, flip_inner={bool(p.get("flip_inner", True))!r})'
            elif op == 'extrude_until':
                if not inputs:
                    raise ValueError('until extrusion target missing')
                target = f'[_b for _group in [{", ".join(inputs)}] for _b in _group]'
                expression = f'scad.extrude_until_rsolid(profile=_profile, target={target}, direction={fmt_vec(p.get("direction", (0, 0, 1)))}, until={str(p.get("until", "NEXT"))!r})'
            else:
                direction = _named(p, 'normal', 'direction', 'vector', default=(0, 0, 1))
                distance = math.sqrt(dot(direction, direction))
                origin = list(_named(p, 'center', 'origin', default=(0, 0, 0)))
                if len(origin) == 2:
                    origin.append(0)
                expression = f'scad.twisted_sweep_rsolid(profile=_profile, distance={fmt_num(distance)}, twist_angle={fmt_num(_named(p, "angle", "twist_angle", default=0))}, axis={fmt_vec(direction)}, origin={fmt_vec(origin)}, guide_radius=1)'
            self.lines.append(f'    {var} = [{expression} for _profile in [{", ".join(refs)}]]')
        elif op == 'revolve':
            profiles = _profiles(step)
            refs = [self.profile(profile, f'{var}_profile{i}') for i, profile in enumerate(profiles)]
            axis, origin = _axis(p)
            angle = _named(p, 'angle', 'arc', 'revolution_arc', default=360)
            if angle < 0:
                angle, axis = -angle, [-float(x) for x in axis]
            self.lines.append(f'    {var} = [scad.revolve_rsolid(profile=_profile, axis={fmt_vec(axis)}, angle={fmt_num(angle)}, origin={fmt_vec(origin)}) for _profile in [{", ".join(refs)}]]')
        elif op == 'loft':
            profiles = step.get('profiles') or []
            refs = [self.profile(profile, f'{var}_section{i}', as_wire=True) for i, profile in enumerate(profiles)]
            if len(refs) < 2:
                raise ValueError('loft needs at least two recorded sections')
            self.lines.append(f'    {var} = [scad.loft_rsolid(profiles=[{", ".join(refs)}], ruled={bool(p.get("ruled", False))!r})]')
        elif op == 'sew_solid':
            if step.get('geometry_error'):
                raise ValueError(step['geometry_error'])
            profiles = step.get('profiles') or []
            if not profiles:
                raise ValueError('solid shell requires recorded planar faces')
            refs = [self.profile(profile, f'{var}_face{i}') for i, profile in enumerate(profiles)]
            self.lines.append(f'    {var}_shell = scad.sew_faces_rshell(faces=[{", ".join(refs)}])')
            self.lines.append(f'    {var} = [scad.make_solid_from_shell_rsolid(shell={var}_shell)]')
        elif op in {'sweep', 'sweep_multi'}:
            profiles = _profiles(step)
            path = step.get('path')
            if not path:
                raise ValueError('sweep path missing')
            path_lines, path_expr = emit_path(path, var + '_path', snapshots=self.snapshots)
            self.lines.extend(path_lines)
            refs = ([self.profile(profile, f'{var}_profile{i}') for i, profile in enumerate(profiles)]
                    if op == 'sweep_multi' or not any(len(profile.get('wires', [])) > 1 for profile in profiles)
                    else [])
            frenet = bool(_named(p, 'is_frenet', 'frenet', default=False))
            if op == 'sweep_multi':
                binormal = p.get('binormal')
                if isinstance(binormal, dict):
                    raise ValueError('multisection sweep binormal wire missing from portable trace')
                self.lines.append(f'    {var} = [scad.sweep_multisection_rsolid(profiles=[{", ".join(refs)}], path={path_expr}, is_frenet={frenet!r}, binormal={fmt_literal(binormal)})]')
            else:
                if p.get('mode') is not None or str(p.get('transition', 'TRANSFORMED')) != 'TRANSFORMED':
                    raise ValueError('sweep mode/transition needs a native advanced sweep operator')
                if any(len(profile.get('wires', [])) > 1 for profile in profiles):
                    pieces = []
                    for index, profile in enumerate(profiles):
                        loops = [self.profile({**profile, 'wires': [wire]}, f'{var}_loop{index}_{i}')
                                 for i, wire in enumerate(profile['wires'])]
                        outer = var + f'_outer{index}'
                        self.lines.append(f'    {outer} = [scad.sweep_rsolid(profile={loops[0]}, path={path_expr}, is_frenet={frenet!r})]')
                        tools = ', '.join(f'scad.sweep_rsolid(profile={loop}, path={path_expr}, is_frenet={frenet!r})' for loop in loops[1:])
                        pieces.append(f'scad.boolean_rsolidlist(left={outer}, right=[{tools}], operation="cut")')
                    self.lines.append(f'    {var} = [_b for _group in [{", ".join(pieces)}] for _b in _group]')
                else:
                    self.lines.append(f'    {var} = [scad.sweep_rsolid(profile=_profile, path={path_expr}, is_frenet={frenet!r}) for _profile in [{", ".join(refs)}]]')
        elif op == 'component':
            if len(inputs) != 1:
                raise ValueError('component requires one parent feature')
            fingerprint = p.get('fingerprint', {})
            if fingerprint.get('bbox') is not None:
                self.uses_ql = True
                selector = fingerprint_selector([fingerprint], 'solid')
                self.lines.append(f'    {var} = {selector}.resolve({inputs[0]})')
            else:
                self.lines.append(f'    {var} = [{inputs[0]}[{int(p["index"])}]]')
        elif op in {'compound', 'copy', 'clean'}:
            self.lines.append(f'    {var} = [ _b for _group in [{", ".join(inputs)}] for _b in _group ]')
        elif op in {'union', 'fuse', 'cut', 'intersect'}:
            if not inputs:
                raise ValueError('boolean inputs missing')
            if len(inputs) == 1:
                self.lines.append(f'    {var} = list({inputs[0]})')
            elif op == 'cut':
                tools = f'[_b for _group in [{", ".join(inputs[1:])}] for _b in _group]'
                self.lines.append(f'    {var} = scad.boolean_rsolidlist(left={inputs[0]}, right={tools}, operation="cut")')
            elif op == 'intersect':
                self.lines.append(f'    {var} = list({inputs[0]})')
                for group in inputs[1:]:
                    self.lines.append(f'    {var} = scad.boolean_rsolidlist(left={var}, right={group}, operation="intersect")')
            else:
                groups = step.get('result_groups')
                if groups:
                    values = []
                    for group in groups:
                        group_refs = [self.variables[x] for x in group]
                        values.append(f'scad.union_rsolid([{", ".join(group_refs)}], tracking_policy="graph")' if len(group_refs) > 1 else f'{group_refs[0]}[0]')
                    self.lines.append(f'    {var} = [{", ".join(values)}]')
                elif step.get('result', {}).get('solid_count', 1) > 1:
                    raise ValueError('disconnected union requires recorded connected operand groups')
                else:
                    self.lines.append(f'    {var} = [scad.union_rsolid([{", ".join(inputs)}], tracking_policy="graph")]')
        elif op in {'fillet', 'chamfer'}:
            selector = fingerprint_selector(step.get('selection', []), 'edge')
            self.uses_ql = True
            if len(inputs) != 1:
                raise ValueError('blend requires one parent feature')
            if op == 'fillet':
                extras = f'radius={fmt_num(p["radius"])}'
            else:
                extras = f'distance={fmt_num(_named(p, "length", "distance", "length1"))}'
                second = _named(p, 'length2', 'distance2')
                if second is not None and abs(float(second) - float(_named(p, 'length', 'distance', 'length1'))) > 1e-9:
                    extras += ', angle=' + fmt_num(math.degrees(math.atan2(float(second), float(_named(p, 'length', 'distance', 'length1')))))
                    direction = p.get('reference_direction')
                    if direction is None:
                        if p.get('reference_directions'):
                            raise ValueError('per-edge chamfer reference normals vary; the native operator requires one reference direction')
                        raise ValueError('asymmetric chamfer requires reference-face normal')
                    extras += ', reference_direction=' + fmt_vec(direction)
            groups = step.get('component_selections')
            if groups is not None:
                self.lines.append(f'    {var} = []')
                for index, selection in enumerate(groups):
                    body = f'{inputs[0]}[{index}]'
                    if selection:
                        local = fingerprint_selector(selection, 'edge')
                        self.lines.append(f'    {var}.append(scad.{op}_rsolid(solid={body}, edges={local}, {extras}))')
                    else:
                        self.lines.append(f'    {var}.append({body})')
            elif self.steps[step['inputs'][0]].get('result', {}).get('solid_count', 1) > 1:
                raise ValueError('multi-body blend requires per-component selections')
            else:
                self.lines.append(f'    {var} = [scad.{op}_rsolid(solid=_b, edges={selector}, {extras}) for _b in {inputs[0]}]')
        elif op == 'draft':
            if len(inputs) != 1:
                raise ValueError('draft requires one parent feature')
            selector = fingerprint_selector(step.get('selection', []), 'face')
            self.uses_ql = True
            plane = p.get('neutral_plane') or p.get('plane') or {}
            angle = _named(p, 'angle', 'draft_angle')
            if angle is None or not isinstance(plane, dict):
                raise ValueError('draft angle or neutral plane missing')
            self.lines.append(f'    {var} = [scad.draft_rsolid(solid=_b, faces_to_draft={selector}, angle={fmt_num(angle)}, plane_origin={fmt_vec(plane.get("origin", (0, 0, 0)))}, plane_normal={fmt_vec(plane.get("normal", (0, 0, 1)))}) for _b in {inputs[0]}]')
        elif op in {'offset', 'shell'}:
            if len(inputs) != 1:
                raise ValueError('offset requires one parent feature')
            selections = step.get('selection', [])
            selector = fingerprint_selector(selections, 'face') if selections else '[]'
            self.uses_ql |= bool(selections)
            amount = _named(p, 'offset', 'amount', 'thickness', 'distance')
            if amount is None:
                raise ValueError('offset distance missing')
            self.lines.append(f'    {var} = [scad.offset_rsolid(solid=_b, amount={fmt_num(amount)}, openings={selector}, tolerance={fmt_num(p.get("tolerance", 1e-4))}, kind={str(p.get("kind", "ARC"))!r}) for _b in {inputs[0]}]')
        elif op == 'split':
            self.split(step, p, inputs, var)
        elif op in {'transform', 'translate', 'rotate', 'mirror', 'scale', 'move', 'moved', 'located', 'locate', 'transform_shape', 'transform_geometry'}:
            self.transform(op, p, inputs, var)
        else:
            raise ValueError(f'unsupported op: {op}')
        components = step.get('result_components', [])
        if components and all(fp.get('bbox') is not None for fp in components):
            # Kernel output order is not stable across environments. Restore the
            # traced component order before indexed selections and modifications.
            self.uses_ql = True
            selectors = [fingerprint_selector([fp], 'solid') for fp in components]
            self.lines.append(f'    {var} = [{", ".join(f"{selector}.resolve({var})[0]" for selector in selectors)}]')
        self.lines.append('')
        self.variables[ident] = var
        self.steps[ident] = step
        self.feature_count += 1

    def primitive(self, op, p, var):
        plane = p.get('plane') or {}
        origin = _named(p, 'origin', 'center', default=plane.get('origin', (0, 0, 0)))
        axis = _named(p, 'axis', default=plane.get('normal', (0, 0, 1)))
        if isinstance(axis, dict):
            origin, axis = axis.get('origin', origin), axis.get('direction', (0, 0, 1))
        x_dir = plane.get('x_dir', (1, 0, 0))
        if op == 'box':
            length = _named(p, 'length', 'x', default=p.get('width'))
            width = _named(p, 'width', 'y', default=p.get('height'))
            height = _named(p, 'height', 'z', default=p.get('depth'))
            u, v = unit(x_dir), unit(cross(unit(axis), unit(x_dir)))
            bottom = [float(origin[i]) + float(length) * u[i] / 2 + float(width) * v[i] / 2 for i in range(3)]
            self.lines.extend([f'    with scad.SimpleWorkplane(origin=(0, 0, 0), normal={fmt_vec(axis)}, x_dir={fmt_vec(x_dir)}):',
                f'        {var} = [scad.make_box_rsolid(width={fmt_num(length)}, height={fmt_num(width)}, depth={fmt_num(height)}, bottom_face_center={fmt_vec([dot(bottom, u), dot(bottom, v), dot(bottom, unit(axis))])})]'])
        elif op in {'cylinder', 'cone'}:
            angle = _named(p, 'angle', 'arc_size', default=360)
            if abs(float(angle) - 360) > 1e-9:
                axis, x_dir = unit(axis), unit(x_dir)
                y_dir = unit(cross(axis, x_dir))
                def world(x, y, z):
                    return [origin[i] + x * x_dir[i] + y * y_dir[i] + z * axis[i] for i in range(3)]
                if op == 'cylinder':
                    radius = float(p['radius'])
                    theta = math.radians(float(angle))
                    start, mid, end = world(radius, 0, 0), world(radius * math.cos(theta / 2), radius * math.sin(theta / 2), 0), world(radius * math.cos(theta), radius * math.sin(theta), 0)
                    edges = [{'kind': 'line', 'start': origin, 'end': start}, {'kind': 'arc', 'start': start, 'mid': mid, 'end': end}, {'kind': 'line', 'start': end, 'end': origin}]
                    profile = {'origin': origin, 'u': x_dir, 'v': y_dir, 'normal': axis, 'wires': [{'edges': edges}]}
                    face = self.profile(profile, var + '_sector')
                    self.lines.append(f'    {var} = [scad.extrude_rsolid(profile={face}, direction={fmt_vec(axis)}, distance={fmt_num(p["height"])})]')
                else:
                    bottom_radius, top_radius = float(_named(p, 'base_radius', 'radius1', 'bottom_radius')), float(_named(p, 'radius2', 'top_radius', default=0))
                    points = [world(0, 0, 0), world(bottom_radius, 0, 0), world(top_radius, 0, float(p['height'])), world(0, 0, float(p['height']))]
                    edges = [{'kind': 'line', 'start': a, 'end': b} for a, b in zip(points, points[1:] + points[:1]) if sum((x - y) ** 2 for x, y in zip(a, b)) > 1e-20]
                    profile = {'origin': origin, 'u': x_dir, 'v': axis, 'normal': cross(x_dir, axis), 'wires': [{'edges': edges}]}
                    face = self.profile(profile, var + '_meridian')
                    self.lines.append(f'    {var} = [scad.revolve_rsolid(profile={face}, axis={fmt_vec(axis)}, angle={fmt_num(angle)}, origin={fmt_vec(origin)})]')
                return
            if op == 'cylinder':
                args = f'radius={fmt_num(p["radius"])}'
            else:
                args = f'bottom_radius={fmt_num(_named(p, "radius1", "bottom_radius", "base_radius"))}, top_radius={fmt_num(_named(p, "radius2", "top_radius", default=0))}'
            self.lines.append(f'    {var} = [scad.make_{op}_rsolid({args}, height={fmt_num(p["height"])}, bottom_face_center={fmt_vec(origin)}, axis={fmt_vec(axis)})]')
        elif op == 'sphere':
            if any(abs(float(p.get(key, default)) - default) > 1e-9 for key, default in [('angle1', -90), ('angle2', 90), ('angle3', 360)]):
                radius, axis, x_dir = float(p['radius']), unit(axis), unit(x_dir)
                theta1, theta2 = math.radians(float(p.get('angle1', -90))), math.radians(float(p.get('angle2', 90)))
                def meridian(theta):
                    return [origin[i] + radius * math.cos(theta) * x_dir[i] + radius * math.sin(theta) * axis[i] for i in range(3)]
                start, mid, end = meridian(theta1), meridian((theta1 + theta2) / 2), meridian(theta2)
                bottom_axis = [origin[i] + radius * math.sin(theta1) * axis[i] for i in range(3)]
                top_axis = [origin[i] + radius * math.sin(theta2) * axis[i] for i in range(3)]
                edges = [{'kind': 'arc', 'start': start, 'mid': mid, 'end': end}]
                edges.extend({'kind': 'line', 'start': a, 'end': b} for a, b in [(end, top_axis), (top_axis, bottom_axis), (bottom_axis, start)] if sum((x - y) ** 2 for x, y in zip(a, b)) > 1e-20)
                profile = {'origin': origin, 'u': x_dir, 'v': axis, 'normal': cross(x_dir, axis), 'wires': [{'edges': edges}]}
                face = self.profile(profile, var + '_meridian')
                self.lines.append(f'    {var} = [scad.revolve_rsolid(profile={face}, axis={fmt_vec(axis)}, angle={fmt_num(p.get("angle3", 360))}, origin={fmt_vec(origin)})]')
                return
            self.lines.append(f'    {var} = [scad.make_sphere_rsolid(radius={fmt_num(p["radius"])}, center={fmt_vec(origin)})]')
        else:
            start = _named(p, 'start_angle', 'angle1', default=0)
            end = _named(p, 'end_angle', 'angle2', default=360)
            if abs(float(start)) > 1e-9 or abs(float(end) - 360) > 1e-9:
                raise ValueError('partial torus tube needs a traced meridian closure profile')
            major, minor = _named(p, 'major_radius', 'radius1'), _named(p, 'minor_radius', 'radius2')
            axis = unit(axis)
            x_dir = unit(x_dir)
            profile_origin = [o + float(major) * x for o, x in zip(origin, x_dir)]
            profile = {'origin': profile_origin, 'u': x_dir, 'v': axis, 'normal': cross(x_dir, axis),
                       'wires': [{'edges': [{'kind': 'circle', 'center': profile_origin, 'radius': minor}]}]}
            face = self.profile(profile, var + '_meridian')
            self.lines.append(f'    {var} = [scad.revolve_rsolid(profile={face}, axis={fmt_vec(axis)}, angle={fmt_num(_named(p, "major_angle", "angle3", "angle", default=360))}, origin={fmt_vec(origin)})]')

    def transform(self, op, p, inputs, var):
        if len(inputs) != 1:
            raise ValueError('transform requires one parent feature')
        expression = '_b'
        matrix = _named(p, 'matrix', 'matrix4x4', 't_matrix', 'location', 'loc')
        if matrix is None and isinstance(p.get('transform'), (dict, list, tuple)):
            matrix = p['transform']
        if matrix is not None:
            try:
                scales, axis, angle, vector = _matrix_operations(matrix)
            except ValueError as error:
                if 'shear' not in str(error):
                    raise
                raw_matrix = matrix.get('matrix') if isinstance(matrix, dict) else matrix
                expression = f'scad.transform_rsolid(solid=_b, matrix={fmt_literal(raw_matrix)})'
                self.lines.append(f'    {var} = [{expression} for _b in {inputs[0]}]')
                return
            if any(abs(x - 1) > 1e-10 for x in scales):
                expression = f'scad.scale_rsolid(solid={expression}, factors={fmt_vec(scales)}, center=(0, 0, 0))'
            if abs(angle) > 1e-10:
                expression = f'scad.rotate_shape(shape={expression}, angle={fmt_num(angle)}, axis={fmt_vec(axis)}, origin=(0, 0, 0))'
            if any(abs(x) > 1e-10 for x in vector):
                expression = f'scad.translate_shape(shape={expression}, vector={fmt_vec(vector)})'
        elif op == 'mirror' or p.get('mirror_plane') is not None:
            plane = p.get('mirror_plane') or p.get('plane') or {}
            expression = f'scad.mirror_shape(shape=_b, plane_origin={fmt_vec(plane.get("origin", (0, 0, 0)))}, plane_normal={fmt_vec(plane.get("normal", (0, 0, 1)))})'
        elif op == 'rotate' or p.get('angle') is not None:
            axis, origin = _axis(p)
            expression = f'scad.rotate_shape(shape=_b, angle={fmt_num(p["angle"])}, axis={fmt_vec(axis)}, origin={fmt_vec(origin)})'
        elif op == 'scale' or p.get('method') == 'scale' or p.get('factor') is not None or p.get('factors') is not None:
            factors = _named(p, 'factors', 'factor', 'scale', default=1)
            if isinstance(factors, (int, float)):
                factors = (factors,) * 3
            expression = f'scad.scale_rsolid(solid=_b, factors={fmt_vec(factors)}, center={fmt_vec(_named(p, "center", "about", default=(0, 0, 0)))})'
        else:
            vector = _named(p, 'vector', 'translation', 'offset')
            if vector is None:
                raise ValueError('transform has no supported parameters')
            expression = f'scad.translate_shape(shape=_b, vector={fmt_vec(vector)})'
        self.lines.append(f'    {var} = [{expression} for _b in {inputs[0]}]')

    def split(self, step, p, inputs, var):
        if len(inputs) != 1:
            raise ValueError('split requires one parent feature')
        plane = _named(p, 'plane', 'bisect_by', 'tool', default={})
        if not isinstance(plane, dict) or 'normal' not in plane:
            raise ValueError('only planar solid splits are supported')
        origin, u, v, normal = frame(plane)
        source_step = self.steps[step['inputs'][0]]
        bbox = source_step.get('result', {}).get('bbox') or self.trace.get('b3d_bbox')
        if not bbox or len(bbox) != 6:
            raise ValueError('split needs the source feature bounding box')
        corners = [(x, y, z) for x in (bbox[0], bbox[3]) for y in (bbox[1], bbox[4]) for z in (bbox[2], bbox[5])]
        projected = [[dot([c[i] - origin[i] for i in range(3)], axis) for c in corners] for axis in (u, v, normal)]
        margin = max(math.sqrt(sum((bbox[i + 3] - bbox[i]) ** 2 for i in range(3))), 1)
        center2 = [(min(a) + max(a)) / 2 for a in projected[:2]]
        width, height = [max(a) - min(a) + margin * 2 for a in projected[:2]]
        depth = max(abs(x) for x in projected[2]) + margin
        tool_origin = [origin[i] + center2[0] * u[i] + center2[1] * v[i] for i in range(3)]
        keep = str(p.get('keep', 'BOTH')).upper().split('.')[-1]
        refs = []
        component_sides = step.get('result_component_sides')
        ordered_sides = component_sides if keep == 'BOTH' and component_sides else ['TOP', 'BOTTOM']
        for side in ordered_sides:
            label = str(side).lower()
            if label not in {'top', 'bottom'}:
                raise ValueError(f'unknown split component side: {side}')
            sign = 1 if label == 'top' else -1
            if keep != 'BOTH' and keep != label.upper():
                continue
            tool = var + '_' + label
            self.lines.extend([f'    with scad.SimpleWorkplane(origin={fmt_vec(tool_origin)}, normal={fmt_vec([sign * x for x in normal])}, x_dir={fmt_vec(u)}):',
                f'        {tool} = scad.make_box_rsolid(width={fmt_num(width)}, height={fmt_num(height)}, depth={fmt_num(depth)}, bottom_face_center=(0, 0, 0))'])
            refs.append(f'scad.boolean_rsolidlist(left={inputs[0]}, right=[{tool}], operation="intersect")')
        if not refs:
            raise ValueError(f'unknown split keep mode: {keep}')
        self.lines.append(f'    {var} = [_piece for _group in [{", ".join(refs)}] for _piece in _group]')

    def replay(self):
        for step in self.trace.get('steps', []):
            before = len(self.lines)
            before_ql = self.uses_ql
            before_sketches = len(self.snapshots)
            before_slugs = dict(self.slugs.counts)
            try:
                self.build_step(step)
                for snapshot in self.snapshots[before_sketches:]:
                    snapshot.update({'feature_id': step.get('id'), 'op': step.get('op'), 'role': 'profile'})
            except (ValueError, KeyError, TypeError, IndexError) as error:
                del self.lines[before:]
                del self.snapshots[before_sketches:]
                self.uses_ql = before_ql
                self.slugs.counts = before_slugs
                self.unsupported.append(f'{step.get("id", "?")} {step.get("op", "?")}: {error}')
        requested = self.trace.get('result_refs') if 'result_refs' in self.trace else self.trace.get('results')
        if requested is None:
            requested = [self.trace['steps'][-1]['id']] if self.trace.get('steps') else []
        if isinstance(requested, str):
            requested = [requested]
        refs = [self.variables[x] for x in requested if isinstance(x, str) and x in self.variables]
        missing = [x for x in requested if x not in self.variables]
        if missing:
            self.unsupported.append(f'final result features unavailable: {missing}')
        if not refs:
            self.unsupported.append('feature tree produced no solid')
        if self.constraints_mode:
            self.recover_constraints()
        count = int(self.trace.get('solid_count') or sum(self.steps[x].get('result', {}).get('solid_count', 1) for x in requested if x in self.steps) or 1)
        source = emit_module(self.stem, self.lines, refs, self.unsupported, self.uses_ql, count)
        return source, {'status': 'partial' if self.unsupported else 'ok', 'feature_count': self.feature_count,
                        'unsupported': self.unsupported, 'result_refs': requested,
                        'notes': [], 'schema_version': '1.0', 'solid_count': count,
                        'artifact_type': 'assembly' if count > 1 else 'part',
                        'sketches': self.snapshots, 'sketch_count': len(self.snapshots),
                        'constraint_recovery': self.constraint_reports}

    def recover_constraints(self):
        """Reuse the source-agnostic CQ inference engine without changing it.

        It admits only geometry-entailed constraints whose production solver
        preserves coordinates. Unsupported entity families retain geometry.
        """
        import sys
        from pathlib import Path
        sibling = str(Path(__file__).resolve().parents[2] / 'cadqueryftc')
        if sibling not in sys.path:
            sys.path.insert(0, sibling)
        from cqftc.constraints import emit_constraint_lines, recover_constraints_guarded
        for snapshot in self.snapshots:
            if snapshot.get('compact'):
                self.constraint_reports.append({'name': snapshot['name'], 'status': 'unsupported',
                    'reason': 'constraint emission is unavailable for compact multi-loop sketches', 'constraints': []})
                continue
            if any(entity['kind'] not in {'point', 'line', 'circle', 'arc'} for entity in snapshot['entities']):
                self.constraint_reports.append({'name': snapshot['name'], 'status': 'unsupported',
                    'reason': 'constraint recovery does not handle ellipse/B-spline entities', 'constraints': []})
                continue
            try:
                report = recover_constraints_guarded(snapshot, timeout=30)
            except Exception as error:
                report = {'status': 'error', 'reason': str(error), 'constraints': []}
            report['name'] = snapshot['name']
            self.constraint_reports.append(report)
            if not report.get('coords_ok'):
                continue
            name = snapshot['name']
            constraints = [line.replace('    s = ', f'    {name} = ').replace('sketch=s,', f'sketch={name},')
                           for line in emit_constraint_lines(report)]
            for index, line in enumerate(self.lines):
                if f'sketch={name}, profile=' in line and ('make_wire_from_sketch_rwire' in line or 'make_face_from_sketch_rface' in line):
                    self.lines[index:index] = constraints
                    break


def replay_trace_to_ftc(trace: Any, *, stem: str = 'part', constraints_mode: bool = False):
    if hasattr(trace, 'to_dict'):
        trace = trace.to_dict()
    if not isinstance(trace, Mapping):
        raise TypeError('trace must be a portable JSON mapping')
    return TraceReplayer(trace, stem, constraints_mode=constraints_mode).replay()
