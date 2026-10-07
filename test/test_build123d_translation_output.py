"""Format and executable geometry tests for build123d FTC translation.

Fixtures model the trace protocol without depending on build123d itself.
"""
from __future__ import annotations
import importlib.util
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/research/build123dftc'))
from b3ftc.replay import replay_trace_to_ftc


def rectangle(x=10, y=6, z=0):
    points = [(0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    return {'origin': (0, 0, z), 'u': (1, 0, 0), 'v': (0, 1, 0),
            'normal': (0, 0, 1), 'wires': [{'edges': [
                {'kind': 'line', 'start': a, 'end': b}
                for a, b in zip(points, points[1:] + points[:1])]}]}


def circle(radius, z=0):
    return {'origin': (0, 0, z), 'u': (1, 0, 0), 'v': (0, 1, 0),
            'normal': (0, 0, 1), 'wires': [{'edges': [
                {'kind': 'circle', 'center': (0, 0, z), 'radius': radius,
                 'normal': (0, 0, 1), 'x_dir': (1, 0, 0)}]}]}


def trace(*steps):
    return {'schema_version': '1.0', 'steps': list(steps),
            'result_refs': [steps[-1]['id']], 'unsupported': []}


class FormatTests(unittest.TestCase):
    def test_vertex_loft_sections_use_keyword_arguments(self):
        source, meta = replay_trace_to_ftc(trace({'id': 's1', 'op': 'loft',
            'profiles': [circle(2), {'kind': 'vertex', 'point': (0, 0, 5)}],
            'parameters': {'ruled': True}}), stem='pointed')
        self.assertEqual(meta['status'], 'ok', meta)
        self.assertIn('scad.make_point_rvertex(x=0, y=0, z=5)', source)

    def test_real_recorded_fixtures_need_no_build123d_dependency(self):
        for path in sorted((ROOT / 'test/build123d_traces').glob('*.trace.json')):
            with self.subTest(fixture=path.name):
                import json
                source, meta = replay_trace_to_ftc(json.loads(path.read_text()), stem=path.stem)
                self.assertEqual(meta['status'], 'ok', meta['unsupported'])
                compile(source, str(path), 'exec')
                self.assertNotIn('import build123d', source)
                self.assertNotIn('load_brep', source)
    def test_sketch_extrusion_and_explicit_module_contract(self):
        source, meta = replay_trace_to_ftc(trace({'id': 's1', 'op': 'extrude',
            'profile': rectangle(), 'parameters': {'direction': (0, 0, 1), 'distance': 4}}), stem='plate')
        self.assertEqual(meta['status'], 'ok', meta)
        self.assertIn('scad.make_sketch_rsketch(', source)
        self.assertIn('scad.make_face_from_sketch_rface(', source)
        self.assertIn('scad.extrude_rsolid(', source)
        self.assertIn("project_root=Path(__file__).parent", source)
        self.assertIn('BODIES = list(bodies)', source)
        self.assertRegex(source, r'feature: extrude \(build, profile=geometry\)')
        for text in ('import build123d', 'import OCP', 'load_brep', '.get_edges()', '.get_faces()'):
            self.assertNotIn(text, source)
        compile(source, '<FTC>', 'exec')

    def test_unknown_feature_blocks_dependents(self):
        source, meta = replay_trace_to_ftc(trace({'id': 's1', 'op': 'unknown'},
            {'id': 's2', 'op': 'translate', 'inputs': ['s1'], 'parameters': {'vector': (1, 0, 0)}}), stem='unknown')
        self.assertEqual(meta['status'], 'partial')
        self.assertTrue(any('unknown' in str(x) for x in meta['unsupported']))
        self.assertIn('feature tree produced no solid', source)

    def test_modifiers_use_individual_fingerprints(self):
        payload = trace({'id': 's1', 'op': 'box', 'parameters': {'length': 10, 'width': 10, 'height': 10}},
            {'id': 's2', 'op': 'fillet', 'inputs': ['s1'], 'parameters': {'radius': 1},
             'selection': [{'kind': 'edge', 'geom_type': 'LINE', 'center': [0, 0, 5], 'length': 10, 'area': 0}]})
        source, meta = replay_trace_to_ftc(payload, stem='filleted')
        self.assertEqual(meta['status'], 'ok', meta)
        self.assertIn('ql.edges()', source)
        self.assertIn('.take(1).exactly(1)', source)
        self.assertIn("ql.prop('geom.length'", source)
        self.assertIn('scad.fillet_rsolid(', source)
        self.assertNotIn('geom.area', source)

    def test_no_final_snapshot_fallback(self):
        source, meta = replay_trace_to_ftc({'steps': [], 'final_brep': 'ignored'}, stem='empty')
        self.assertEqual(meta['status'], 'partial')
        self.assertNotIn('ignored', source)
        self.assertNotIn('load_brep', source)

    def test_explicit_empty_results_do_not_promote_unused_tool(self):
        payload = trace({'id': 's1', 'op': 'box', 'parameters': {'length': 1, 'width': 2, 'height': 3}})
        payload['result_refs'] = []
        source, meta = replay_trace_to_ftc(payload)
        self.assertEqual(meta['status'], 'partial')
        self.assertIn('feature tree produced no solid', source)

    def test_draft_uses_face_predicate_and_neutral_plane(self):
        payload = trace({'id': 's1', 'op': 'box', 'parameters': {'length': 2, 'width': 2, 'height': 3}},
            {'id': 's2', 'op': 'draft', 'inputs': ['s1'], 'parameters': {'angle': 5,
                'neutral_plane': {'origin': (0, 0, 0), 'normal': (0, 0, 1)}},
             'selection': [{'kind': 'face', 'geom_type': 'PLANE', 'center': (2, 1, 1.5), 'area': 6, 'length': 0}]})
        source, meta = replay_trace_to_ftc(payload)
        self.assertEqual(meta['status'], 'ok', meta)
        self.assertIn('scad.draft_rsolid(', source)
        self.assertIn('faces_to_draft=ql.faces()', source)
        self.assertNotIn('geom.length', source)
        compile(source, '<FTC>', 'exec')


class GeometryTests(unittest.TestCase):
    def test_real_recorded_fixtures_reconcile(self):
        import json
        for path in sorted((ROOT / 'test/build123d_traces').glob('*.trace.json')):
            with self.subTest(fixture=path.name):
                payload = json.loads(path.read_text())
                self.build(payload, payload['b3d_volume'])
    def build(self, payload, expected, *, constraints_mode=False):
        source, meta = replay_trace_to_ftc(payload, stem='geometry', constraints_mode=constraints_mode)
        self.assertEqual(meta['status'], 'ok', meta)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'model.ftc.py'
            path.write_text(source)
            spec = importlib.util.spec_from_file_location('ftc_geometry_' + path.parent.name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.build()
            self.assertEqual(len(module.BODIES), payload.get('solid_count', 1))
            from OCP.BRepCheck import BRepCheck_Analyzer
            self.assertTrue(all(BRepCheck_Analyzer(body.wrapped).IsValid() for body in module.BODIES))
            from OCP.BRepGProp import BRepGProp
            from OCP.GProp import GProp_GProps
            def accurate_volume(body):
                props = GProp_GProps()
                BRepGProp.VolumePropertiesGK_s(body.wrapped, props, 1e-9, True, True)
                return float(props.Mass())
            volume = sum(accurate_volume(body) for body in module.BODIES)
            self.assertAlmostEqual(volume, expected, delta=max(abs(expected), 1) * 1e-6)

    def test_extruded_rectangle(self):
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': rectangle(),
            'parameters': {'direction': (0, 0, 1), 'distance': 4}}), 240)

    def test_recovered_constraints_preserve_rectangle_geometry(self):
        payload = trace({'id': 's1', 'op': 'extrude', 'profile': rectangle(),
            'parameters': {'direction': (0, 0, 1), 'distance': 4}})
        self.build(payload, 240, constraints_mode=True)
        source, meta = replay_trace_to_ftc(payload, constraints_mode=True)
        self.assertTrue(meta['sketches'])
        self.assertEqual(meta['constraint_recovery'][0]['status'], 'riveted')
        self.assertIn('scad.constrain_', source)

    def test_face_with_circle_hole(self):
        profile = circle(5)
        profile['wires'].extend(circle(2)['wires'])
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': profile,
            'parameters': {'direction': (0, 0, -1), 'distance': 3}}), math.pi * 21 * 3)

    def test_clockwise_polygon_hole_is_subtractive(self):
        profile = circle(5)
        points = [(2, -1, 0), (-2, -1, 0), (-2, 1, 0), (2, 1, 0)]
        profile['wires'].append({'edges': [{'kind': 'line', 'start': a, 'end': b}
            for a, b in zip(points, points[1:] + points[:1])]})
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': profile,
            'parameters': {'direction': (0, 0, 1), 'distance': 3}}), (math.pi * 25 - 8) * 3)

    def test_explicit_boolean_cut(self):
        self.build(trace({'id': 's1', 'op': 'box', 'parameters': {'length': 10, 'width': 10, 'height': 5}},
            {'id': 's2', 'op': 'cylinder', 'parameters': {'radius': 2, 'height': 5, 'origin': (5, 5, 0)}},
            {'id': 's3', 'op': 'cut', 'inputs': ['s1', 's2']}), 500 - math.pi * 20)

    def test_loft_circle_sections(self):
        self.build(trace({'id': 's1', 'op': 'loft', 'profiles': [circle(2), circle(4, 6)],
            'parameters': {'ruled': True}}), math.pi * 6 * (4 + 8 + 16) / 3)

    def test_native_multisection_sweep(self):
        self.build(trace({'id': 's1', 'op': 'sweep_multi', 'profiles': [circle(2), circle(4, 6)],
            'path': {'edges': [{'kind': 'line', 'start': (0, 0, 0), 'end': (0, 0, 6)}]},
            'parameters': {'is_frenet': False}}), 56 * math.pi)

    def test_native_tapered_extrusion(self):
        top_radius = 4 - 6 * math.tan(math.radians(15))
        self.build(trace({'id': 's1', 'op': 'extrude_taper', 'profile': circle(4),
            'parameters': {'direction': (0, 0, 6), 'taper': 15}}),
            math.pi * 6 * (16 + 4 * top_radius + top_radius ** 2) / 3)

    def test_native_until_extrusion(self):
        self.build(trace({'id': 's1', 'op': 'box',
            'parameters': {'length': 10, 'width': 10, 'height': 3, 'origin': (-5, -5, 5)}},
            {'id': 's2', 'op': 'extrude_until', 'inputs': ['s1'], 'profile': circle(1),
             'parameters': {'direction': (0, 0, 1), 'until': 'NEXT'}}), 5 * math.pi)

    def test_native_twisted_extrusion(self):
        self.build(trace({'id': 's1', 'op': 'extrude_twist', 'profile': rectangle(),
            'parameters': {'normal': (0, 0, 4), 'center': (0, 0, 0), 'angle': 90}}), 240)

    def test_affine_shear_preserves_volume(self):
        self.build(trace({'id': 's1', 'op': 'box', 'parameters': {'length': 10, 'width': 6, 'height': 4}},
            {'id': 's2', 'op': 'transform', 'inputs': ['s1'], 'parameters': {'matrix': [
                [1, .5, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}}), 240)

    def test_both_split_preserves_original_component_order(self):
        self.build(trace({'id': 's1', 'op': 'box',
            'parameters': {'length': 2, 'width': 3, 'height': 8},
            'result': {'bbox': [0, 0, 0, 2, 3, 8], 'solid_count': 1}},
            {'id': 's2', 'op': 'split', 'inputs': ['s1'],
             'parameters': {'tool': {'origin': (0, 0, 2), 'normal': (0, 0, 1)}, 'keep': 'BOTH'},
             'result_component_sides': ['BOTTOM', 'TOP']},
            {'id': 's3', 'op': 'component', 'inputs': ['s2'], 'parameters': {'index': 0}}), 12)

    def test_exact_ellipse_sketch(self):
        profile = circle(2)
        profile['wires'][0]['edges'] = [{'kind': 'ellipse', 'center': (0, 0, 0),
            'major_radius': 4, 'minor_radius': 2, 'x_dir': (1, 0, 0), 'y_dir': (0, 1, 0)}]
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': profile,
            'parameters': {'direction': (0, 0, 1), 'distance': 3}}), math.pi * 8 * 3)

    def test_translate_preserves_volume(self):
        self.build(trace({'id': 's1', 'op': 'sphere', 'parameters': {'radius': 3}},
            {'id': 's2', 'op': 'translate', 'inputs': ['s1'], 'parameters': {'vector': (5, -8, 2)}}), 36 * math.pi)

    def test_partial_cylinder(self):
        self.build(trace({'id': 's1', 'op': 'cylinder',
            'parameters': {'radius': 3, 'height': 4, 'angle': 180}}), 18 * math.pi)

    def test_partial_cone(self):
        self.build(trace({'id': 's1', 'op': 'cone',
            'parameters': {'base_radius': 3, 'top_radius': 0, 'height': 4, 'angle': 90}}), 3 * math.pi)

    def test_partial_sphere(self):
        self.build(trace({'id': 's1', 'op': 'sphere',
            'parameters': {'radius': 3, 'angle1': 0, 'angle2': 90, 'angle3': 360}}), 18 * math.pi)

    def test_closed_rational_spline_profile(self):
        profile = circle(1)
        poles = [(1, 0, 0), (1, 1, 0), (0, 1, 0), (-1, 1, 0), (-1, 0, 0),
                 (-1, -1, 0), (0, -1, 0), (1, -1, 0), (1, 0, 0)]
        profile['wires'][0]['edges'] = [{'kind': 'bspline', 'poles': poles, 'degree': 2,
            'knots': [0, .25, .5, .75, 1], 'multiplicities': [3, 2, 2, 2, 3],
            'weights': [1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1, math.sqrt(.5), 1],
            'start': poles[0], 'end': poles[-1]}]
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': profile,
            'parameters': {'direction': [0, 0, 1], 'distance': 2}}), 2 * math.pi)

    def test_reversed_cubic_basis_preserves_entire_curve(self):
        profile = circle(1)
        poles = [(0, 0, 0), (0, 3, 0), (2, 4, 0), (4, 0, 0)]
        profile['wires'][0]['edges'] = [{'kind': 'bezier', 'poles': poles, 'degree': 3,
            'start': poles[-1], 'end': poles[0], 'reversed': True},
            {'kind': 'line', 'start': poles[0], 'end': poles[-1]}]
        # Exact Green-integral area of this cubic and its closing chord is 7.5.
        self.build(trace({'id': 's1', 'op': 'extrude', 'profile': profile,
            'parameters': {'direction': [0, 0, 1], 'distance': 2}}), 15)

    def test_multi_body_is_complete_assembly(self):
        payload = trace({'id': 's1', 'op': 'box', 'parameters': {'length': 2, 'width': 3, 'height': 4}},
            {'id': 's2', 'op': 'box', 'parameters': {'length': 4, 'width': 2, 'height': 3, 'origin': [20, 0, 0]}},
            {'id': 's3', 'op': 'compound', 'inputs': ['s1', 's2']})
        payload['solid_count'] = 2
        self.build(payload, 48)
        source, meta = replay_trace_to_ftc(payload)
        self.assertEqual(meta['artifact_type'], 'assembly')
        self.assertIn('@scad.assemble(', source)


if __name__ == '__main__':
    unittest.main()
