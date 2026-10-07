"""Deterministic FTC formatting and topology-fingerprint QL selectors.

This module has no CAD dependency: generated programs use only SimpleCADAPI.
"""
from __future__ import annotations
import math
import re
from typing import Any, Mapping, Sequence

ROLES = frozenset({'build', 'add', 'subtract', 'intersect', 'modify', 'pattern', 'annotate'})


def fmt_num(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('non-finite geometry parameter')
    if abs(number) < 1e-12:
        number = 0.0
    return format(number, '.15g')


def fmt_vec(vector: Sequence[float]) -> str:
    return '(' + ', '.join(fmt_num(v) for v in vector) + (',' if len(vector) == 1 else '') + ')'


def fmt_literal(value: Any) -> str:
    if value is None or isinstance(value, (bool, str)):
        return repr(value)
    if isinstance(value, (int, float)):
        return fmt_num(value)
    if isinstance(value, (list, tuple)):
        return '[' + ', '.join(fmt_literal(v) for v in value) + ']'
    if isinstance(value, Mapping):
        return '{' + ', '.join(repr(k) + ': ' + fmt_literal(v) for k, v in value.items()) + '}'
    raise ValueError(f'unsupported literal type: {type(value).__name__}')


class SlugAllocator:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def allocate(self, name: str) -> str:
        slug = re.sub('[^a-z0-9]+', '-', str(name).lower()).strip('-') or 'feature'
        count = self.counts.get(slug, 0) + 1
        self.counts[slug] = count
        return slug if count == 1 else f'{slug}-{count}'


def block_header(slug: str, role: str, tiers: Sequence[str] = ()) -> str:
    if role not in ROLES:
        raise ValueError(f'invalid FTC role: {role}')
    return f"    # ---- feature: {slug} ({', '.join([role, *tiers])}) ----"


def fingerprint_selector(fingerprints: Sequence[Mapping[str, Any]], kind: str, tolerance: float = 1e-4) -> str:
    """Union individual fingerprint predicates; never select a wide bounding band.

    Each traced edge/face gets its own conjunction. This preserves a disjoint
    selected set whose bounding box could otherwise include unrelated topology.
    """
    predicates = []
    seen = set()
    for fp in fingerprints:
        if fp.get('kind', kind) != kind:
            continue
        terms = []
        geom_type = fp.get('geom_type') or fp.get('type')
        if geom_type:
            terms.append(f"ql.prop('geom.type', '==', {str(geom_type).upper()!r})")
        for name in ('center', 'normal'):
            values = fp.get(name)
            if values is not None:
                for axis, value in zip('xyz', values):
                    tolerance_here = 1e-5 if name == 'normal' else tolerance
                    value = round(float(value), 10)
                    terms.extend([
                        f"ql.prop('geom.{name}.{axis}', '>=', {fmt_num(value - tolerance_here)})",
                        f"ql.prop('geom.{name}.{axis}', '<=', {fmt_num(value + tolerance_here)})",
                    ])
        for name in ('length', 'area', 'radius'):
            if (kind == 'edge' and name == 'area') or (kind == 'face' and name == 'length'):
                continue
            if fp.get(name) is not None:
                value = float(fp[name])
                delta = max(tolerance, abs(value) * 1e-8)
                terms.extend([
                    f"ql.prop('geom.{name}', '>=', {fmt_num(value - delta)})",
                    f"ql.prop('geom.{name}', '<=', {fmt_num(value + delta)})",
                ])
        if not terms:
            raise ValueError(f'{kind} selection lacks geometric fingerprints')
        predicate = 'ql.and_(' + ', '.join(terms) + ')'
        if predicate not in seen:
            seen.add(predicate)
            predicates.append(predicate)
    if not predicates:
        raise ValueError(f'{kind} selection is empty')
    combined = predicates[0] if len(predicates) == 1 else 'ql.or_(' + ', '.join(predicates) + ')'
    count = len([fp for fp in fingerprints if fp.get('kind', kind) == kind])
    return f'ql.{kind}s().where({combined}).take({count}).exactly({count})'


def emit_module(stem: str, lines: Sequence[str], refs: Sequence[str], unsupported: Sequence[str], uses_ql: bool, solid_count: int = 1) -> str:
    part_id = 'b3d-' + (re.sub('[^A-Za-z0-9._-]+', '-', stem).strip('-.') or 'part')
    result = [f'"""FTC generated from build123d feature trace: {stem.replace(chr(34), chr(39))}."""',
              '', 'from pathlib import Path', '', 'import simplecadapi as scad']
    if uses_ql:
        result.append('from simplecadapi import ql')
    result.extend(['', 'BODIES = None', '', ''])
    if solid_count <= 1:
        result.extend([f"@scad.part(id={part_id!r}, revision='1.0.0', project_root=Path(__file__).parent)",
                       'def build() -> scad.Part:'])
    else:
        result.append('def _build_bodies():')
    result.extend(lines)
    for note in unsupported:
        result.append('    # untranslated: ' + str(note).replace('\n', ' '))
    if refs:
        result.extend([f'    bodies = [_b for _group in [{", ".join(refs)}] for _b in _group]',
                       '    global BODIES', '    BODIES = list(bodies)',
                       '    return bodies[0]' if solid_count <= 1 else '    return bodies'])
    else:
        result.append("    raise RuntimeError('feature tree produced no solid')")
    if solid_count > 1:
        for index in range(solid_count):
            result.extend(['', '', f"@scad.part(id={f'{part_id}-body-{index + 1}'!r}, revision='1.0.0', project_root=Path(__file__).parent)",
                           f'def _build_body_{index + 1}() -> scad.Part:',
                           f'    return _build_bodies()[{index}]'])
        result.extend(['', '', 'def build():',
                       '    parts = [' + ', '.join(f'_build_body_{i + 1}()' for i in range(solid_count)) + ']',
                       f"    @scad.assemble(id={part_id!r}, revision='1.0.0', definitions=parts, project_root=Path(__file__).parent)",
                       '    def _build_assembly():',
                       '        # ---- feature: body-components (build) ----',
                       f'        assembly = scad.make_assembly_rassembly(assembly_id={part_id!r})',
                       '        for index, item in enumerate(parts):',
                       "            component_id = f'body-{index + 1}'",
                       '            assembly = scad.add_component_rassembly(assembly=assembly, item=item.value, component_id=component_id, placement=scad.identity_placement_rplacement())',
                       '            assembly = scad.ground_component_rassembly(assembly=assembly, component_id=component_id)',
                       '        return assembly', '    return _build_assembly()'])
    return '\n'.join(result) + '\n'
