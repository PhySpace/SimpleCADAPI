from __future__ import annotations

import json
import math
import unittest
from copy import deepcopy
from unittest import mock

import simplecadapi as scad
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Cylinder


class TestSurfaceApi(unittest.TestCase):
    @staticmethod
    def _line_wire(start, end):
        return scad.make_wire_from_edges_rwire([scad.make_line_redge(start, end)])

    def test_public_surface_namespace_and_basic_faces(self):
        self.assertIs(
            scad.surface.make_bezier_surface_rface, scad.make_bezier_surface_rface
        )
        self.assertIs(
            scad.surface.make_cylindrical_surface_rface,
            scad.make_cylindrical_surface_rface,
        )
        self.assertIs(
            scad.surface.make_solid_from_shell_rsolid,
            scad.make_solid_from_shell_rsolid,
        )
        self.assertIs(scad.surface.SurfaceBoundary, scad.SurfaceBoundary)

        bezier = scad.make_bezier_surface_rface(
            [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]]
        )
        fitted = scad.fit_point_grid_rface(
            [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]],
            degree_min=1,
            degree_max=3,
        )

        self.assertIsInstance(bezier, scad.Face)
        self.assertIsInstance(fitted, scad.Face)
        self.assertAlmostEqual(bezier.get_area(), 1.0, places=6)
        self.assertAlmostEqual(fitted.get_area(), 1.0, places=6)

    def test_cylindrical_surface_periodic_trim_and_replay(self):
        def point(angle, z):
            return (2.0 * math.cos(angle), 2.0 * math.sin(angle), z)

        with scad.GraphSession() as session:
            carrier = scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, 2.0 * math.pi),
                (0.0, 2.0),
                tag_prefix="carrier",
            )
            edges = [
                scad.make_three_point_arc_redge(
                    point(0.5, 0.0), point(1.5, 0.0), point(2.5, 0.0)
                ),
                scad.make_line_redge(point(2.5, 0.0), point(2.5, 2.0)),
                scad.make_three_point_arc_redge(
                    point(2.5, 2.0), point(1.5, 2.0), point(0.5, 2.0)
                ),
                scad.make_line_redge(point(0.5, 2.0), point(0.5, 0.0)),
            ]
            outer = scad.make_wire_from_edges_rwire(edges)
            trimmed = scad.trim_surface_rface(carrier, outer, tag_prefix="trimmed")

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        self.assertEqual(
            BRepAdaptor_Surface(carrier.wrapped).GetType(), GeomAbs_Cylinder
        )
        self.assertEqual(
            BRepAdaptor_Surface(trimmed.wrapped).GetType(), GeomAbs_Cylinder
        )
        self.assertAlmostEqual(carrier.get_area(), 8.0 * math.pi, places=6)
        self.assertAlmostEqual(trimmed.get_area(), 8.0, places=5)
        self.assertAlmostEqual(replayed.get_area(), trimmed.get_area(), places=7)
        self.assertIn("trimmed.face", scad.list_tags(replayed))

    def test_cylindrical_surface_rejects_kernel_degenerate_spans(self):
        with self.assertRaisesRegex(scad.SimpleCADError, "u_range"):
            scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, 1.0001e-12),
                (0.0, 2.0),
            )
        with self.assertRaisesRegex(scad.SimpleCADError, "v_range"):
            scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, 1.0),
                (0.0, 1.0e-8),
            )

    def test_cylindrical_surface_uses_radians_and_model_length_units(self):
        carrier = scad.make_cylindrical_surface_rface(
            scad.var("radius", 0.2, unit="cm"),
            (0.0, scad.var("u_max", math.pi, unit="1")),
            (
                scad.var("v_min", 0.0, unit="cm"),
                scad.var("v_max", 0.2, unit="cm"),
            ),
            tolerance=scad.var("surface_tol", 0.001, unit="mm"),
        )

        self.assertAlmostEqual(carrier.get_area(), 4.0 * math.pi, places=6)
        with self.assertRaisesRegex(scad.SimpleCADError, "unitless raw radians"):
            scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, scad.var("u_max", math.pi, unit="rad")),
                (0.0, 2.0),
            )
        with self.assertRaisesRegex(
            scad.SimpleCADError, "tolerance must use model length"
        ):
            scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, math.pi),
                (0.0, 2.0),
                tolerance=scad.var("angular_tol", 0.001, unit="rad"),
            )

    def test_periodic_trim_rejects_wire_outside_partial_carrier(self):
        def point(angle, z):
            return (2.0 * math.cos(angle), 2.0 * math.sin(angle), z)

        carrier = scad.make_cylindrical_surface_rface(
            2.0,
            (0.0, 1.0),
            (0.0, 2.0),
        )
        outer = scad.make_wire_from_edges_rwire(
            [
                scad.make_three_point_arc_redge(
                    point(2.0, 0.0), point(2.25, 0.0), point(2.5, 0.0)
                ),
                scad.make_line_redge(point(2.5, 0.0), point(2.5, 2.0)),
                scad.make_three_point_arc_redge(
                    point(2.5, 2.0), point(2.25, 2.0), point(2.0, 2.0)
                ),
                scad.make_line_redge(point(2.0, 2.0), point(2.0, 0.0)),
            ]
        )

        with self.assertRaisesRegex(scad.SimpleCADError, "bounded carrier"):
            scad.trim_surface_rface(carrier, outer)

    def test_periodic_trim_rejects_holes_explicitly(self):
        carrier = scad.make_cylindrical_surface_rface(
            2.0,
            (0.0, 2.0 * math.pi),
            (0.0, 2.0),
        )
        outer = scad.make_rectangle_rwire(1.0, 1.0, center=(2.0, 0.0, 1.0))
        hole = scad.make_rectangle_rwire(0.25, 0.25, center=(2.0, 0.0, 1.0))

        with self.assertRaisesRegex(scad.SimpleCADError, "holes is not supported"):
            scad.trim_surface_rface(carrier, outer, holes=[hole])

    def test_periodic_trim_rejects_loop_spanning_more_than_one_period(self):
        carrier = scad.make_cylindrical_surface_rface(
            2.0,
            (0.0, 2.0 * math.pi),
            (0.0, 2.0),
        )
        outer = scad.make_wire_from_edges_rwire(
            [
                scad.make_helix_redge(1.0, 2.0, 2.0),
                scad.make_line_redge((2.0, 0.0, 2.0), (2.0, 0.0, 0.0)),
            ]
        )

        with mock.patch(
            "simplecadapi.kernel.ocp_surfaces.BRepAlgoAPI_Common",
            side_effect=AssertionError("boolean construction must not run"),
        ):
            with self.assertRaisesRegex(
                scad.SimpleCADError,
                "bounded carrier parameter domain",
            ):
                scad.trim_surface_rface(carrier, outer)

    def test_periodic_trim_converts_linear_tolerance_to_angular_tolerance(self):
        def point(angle, z):
            return (100.0 * math.cos(angle), 100.0 * math.sin(angle), z)

        carrier = scad.make_cylindrical_surface_rface(
            100.0,
            (0.0, 1.0),
            (0.0, 2.0),
        )
        outer = scad.make_wire_from_edges_rwire(
            [
                scad.make_three_point_arc_redge(
                    point(1.05, 0.0), point(1.075, 0.0), point(1.10, 0.0)
                ),
                scad.make_line_redge(point(1.10, 0.0), point(1.10, 2.0)),
                scad.make_three_point_arc_redge(
                    point(1.10, 2.0), point(1.075, 2.0), point(1.05, 2.0)
                ),
                scad.make_line_redge(point(1.05, 2.0), point(1.05, 0.0)),
            ]
        )

        with self.assertRaisesRegex(scad.SimpleCADError, "bounded carrier"):
            scad.trim_surface_rface(carrier, outer, tolerance=0.2)

    def test_solid_from_closed_shell_replays(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 2.0, 3.0)
            shell = scad.sew_faces_rshell(box._iter_faces())
            shell = scad.apply_tag_rselection(
                shell,
                scad.ql.faces(),
                "role.preserved_face",
            )
            source_face_tags = {face.topo_id for face in shell._iter_faces()}
            solid = scad.make_solid_from_shell_rsolid(shell, tag_prefix="body")

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        self.assertIsInstance(solid, scad.Solid)
        self.assertAlmostEqual(solid.get_volume(), 6.0, places=6)
        self.assertAlmostEqual(replayed.get_volume(), solid.get_volume(), places=7)
        self.assertIn("body.solid", scad.list_tags(replayed))
        self.assertEqual(solid._get_runtime("semantic.lineage.coverage"), "partial")
        self.assertTrue(
            all(
                face.topo_id in source_face_tags
                and "role.preserved_face" in scad.list_tags(face)
                for face in solid._iter_faces()
            )
        )
        self.assertTrue(
            all(
                "role.preserved_face" in scad.list_tags(face)
                for face in replayed._iter_faces()
            )
        )

    def test_trim_replays_with_semantically_tagged_inputs(self):
        with scad.GraphSession() as session:
            carrier = scad.make_bezier_surface_rface(
                [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
            )
            outer = scad.make_rectangle_rwire(4.0, 4.0)
            carrier = scad.apply_tag(carrier, "role.trim_carrier")
            outer = scad.apply_tag(outer, "role.trim_outer")
            trimmed = scad.trim_surface_rface(carrier, outer)

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        self.assertAlmostEqual(replayed.get_area(), trimmed.get_area(), places=7)
        for result in (trimmed, replayed):
            self.assertEqual(
                sorted(witness.binding.tag for witness in result._tag_lineage),
                ["role.trim_carrier", "role.trim_outer"],
            )
            self.assertTrue(
                all(witness.coverage == "partial" for witness in result._tag_lineage)
            )
            self.assertEqual(
                result._get_runtime("semantic.lineage.coverage"), "partial"
            )

    def test_solid_from_shell_rejects_open_shell(self):
        face = scad.make_bezier_surface_rface(
            [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]]
        )
        shell = scad.sew_faces_rshell([face])

        with self.assertRaisesRegex(scad.SimpleCADError, "closed shell"):
            scad.make_solid_from_shell_rsolid(shell)

    def test_shell_scoped_face_tag_replays(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 2.0, 3.0)
            shell = scad.sew_faces_rshell(box._iter_faces())
            tagged_face = scad.apply_tag(
                shell.get_faces(0),
                "role.shell_face",
            )
            session.capture_result(value=tagged_face)

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        self.assertIsInstance(replayed, scad.Face)
        self.assertIn("role.shell_face", scad.list_tags(replayed))

    def test_sewing_does_not_copy_tags_with_no_lineage_policy(self):
        box = scad.make_box_rsolid(1.0, 2.0, 3.0)
        source = box.get_faces(0)
        tagged = scad.apply_tag_rselection(
            source,
            [source],
            "role.local_only",
            lineage_policy=scad.LineagePolicy.NONE,
        )

        sewn = scad.sew_faces_rshell([tagged])

        self.assertNotIn("role.local_only", scad.list_tags(sewn.get_faces(0)))

    def test_workplane_bezier_model_replay_preserves_geometry_and_tag(self):
        with scad.GraphSession() as session:
            with scad.Workplane(
                origin=(10.0, 20.0, 30.0),
                normal=(0.0, 1.0, 0.0),
                x_dir=(1.0, 0.0, 0.0),
            ):
                original = scad.make_bezier_surface_rface(
                    [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 1)]],
                    tag_prefix="skin",
                )

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        original_center = original.get_center()
        replayed_center = replayed.get_center()

        self.assertIsInstance(replayed, scad.Face)
        self.assertAlmostEqual(replayed.get_area(), original.get_area(), places=8)
        self.assertAlmostEqual(replayed_center.x, original_center.x, places=8)
        self.assertAlmostEqual(replayed_center.y, original_center.y, places=8)
        self.assertAlmostEqual(replayed_center.z, original_center.z, places=8)
        self.assertIn("skin.face", scad.list_tags(replayed))

    def test_derived_surface_builders_and_replay(self):
        with scad.GraphSession() as session:
            profile_edges = [
                scad.make_line_redge((0, 0, 0), (1, 0, 0)),
                scad.make_line_redge((0, 1, 0), (1, 1, 0)),
            ]
            guide_edges = [
                scad.make_line_redge((0, 0, 0), (0, 1, 0)),
                scad.make_line_redge((1, 0, 0), (1, 1, 0)),
            ]
            gordon = scad.make_gordon_surface_rface(profile_edges, guide_edges)

            points = [(0, 0, 1), (2, 0, 1), (2, 2, 1), (0, 2, 1)]
            edges = [
                scad.make_line_redge(points[index], points[(index + 1) % 4])
                for index in range(4)
            ]
            patch = scad.make_surface_patch_rface(
                [scad.SurfaceBoundary(edge) for edge in edges],
                tag_prefix="patch",
            )
            session.capture_result(value=[gordon, patch])

        replayed = scad.replay_model_json(scad.export_model_json(session))
        self.assertEqual(len(replayed), 2)
        self.assertAlmostEqual(replayed[0].get_area(), gordon.get_area(), places=7)
        self.assertAlmostEqual(replayed[1].get_area(), patch.get_area(), places=7)
        self.assertEqual(len(replayed[1]._iter_edges()), 4)
        self.assertIn("patch.face", scad.list_tags(replayed[1]))

    def test_shared_boundary_gordon_patches_sew_into_closed_solid(self):
        side = 40.0
        amplitude = 10.0
        samples = 9

        def wave(u, v):
            envelope = math.sin(math.pi * u) ** 2 * math.sin(math.pi * v) ** 2
            return amplitude * envelope * math.sin(4 * math.pi * u) * math.sin(6 * math.pi * v)

        def corner(label):
            return tuple((1 if c == "+" else -1) * side for c in label)

        def point_on(face, u, v):
            a = (u - 0.5) * 2 * side
            b = (v - 0.5) * 2 * side
            offset = wave(u, v)
            return {
                "+z": (a, b, side + offset),
                "-z": (a, b, -side - offset),
                "+x": (side + offset, a, b),
                "-x": (-side - offset, a, b),
                "+y": (a, side + offset, b),
                "-y": (a, -side - offset, b),
            }[face]

        loops = {
            "+z": ("--+", "+-+", "+++", "-++"),
            "-z": ("---", "+--", "++-", "-+-"),
            "+x": ("+--", "++-", "+++", "+-+"),
            "-x": ("---", "-+-", "-++", "--+"),
            "+y": ("-+-", "++-", "+++", "-++"),
            "-y": ("---", "+--", "+-+", "--+"),
        }

        shared = {}
        for face_corners in loops.values():
            for first, second in zip(face_corners, face_corners[1:] + face_corners[:1]):
                key = tuple(sorted((first, second)))
                if key not in shared:
                    shared[key] = scad.make_line_redge(corner(key[0]), corner(key[1]))
        self.assertEqual(len(shared), 12)

        faces = []
        for face, corners in loops.items():
            profiles = []
            for row in range(samples):
                v = row / (samples - 1)
                if row == 0:
                    edge = shared[tuple(sorted((corners[0], corners[1])))]
                elif row == samples - 1:
                    edge = shared[tuple(sorted((corners[3], corners[2])))]
                else:
                    edge = scad.make_interpolated_spline_redge(
                        points=[point_on(face, column / (samples - 1), v) for column in range(samples)],
                        tolerance=1e-5,
                    )
                profiles.append(edge)
            guides = []
            for column in range(samples):
                u = column / (samples - 1)
                if column == 0:
                    edge = shared[tuple(sorted((corners[0], corners[3])))]
                elif column == samples - 1:
                    edge = shared[tuple(sorted((corners[1], corners[2])))]
                else:
                    edge = scad.make_interpolated_spline_redge(
                        points=[point_on(face, u, row / (samples - 1)) for row in range(samples)],
                        tolerance=1e-5,
                    )
                guides.append(edge)
            faces.append(scad.make_gordon_surface_rface(profiles, guides, tolerance=1e-4))

        shell = scad.sew_faces_rshell(faces=faces, tolerance=1e-5)
        self.assertTrue(shell.is_closed())
        self.assertEqual(len(list(shell._iter_faces())), 6)

        solid = scad.make_solid_from_shell_rsolid(shell)
        self.assertIsInstance(solid, scad.Solid)
        self.assertAlmostEqual(solid.get_volume(), 512019.199, delta=2.0)
        self.assertTrue(all(face.get_area() > 4 * side * side for face in solid._iter_faces()))

    def test_trim_surface_with_hole_and_replay(self):
        with scad.GraphSession() as session:
            carrier = scad.make_bezier_surface_rface(
                [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
            )
            outer = scad.make_rectangle_rwire(4.0, 4.0)
            hole = scad.make_rectangle_rwire(1.0, 1.0)
            trimmed = scad.trim_surface_rface(
                carrier,
                outer,
                holes=[hole],
                tag_prefix="trimmed",
            )

        replayed = scad.replay_model_json(scad.export_model_json(session))[0]
        self.assertIsInstance(trimmed, scad.Face)
        self.assertAlmostEqual(trimmed.get_area(), 15.0, places=6)
        self.assertAlmostEqual(replayed.get_area(), trimmed.get_area(), places=7)
        self.assertEqual(len(trimmed._iter_wires()), 2)
        self.assertIn("trimmed.face", scad.list_tags(replayed))

    def test_trim_preserves_existing_carrier_holes(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        bounded = scad.trim_surface_rface(
            carrier,
            scad.make_rectangle_rwire(4.0, 4.0),
            holes=[scad.make_rectangle_rwire(2.0, 2.0)],
        )

        trimmed = scad.trim_surface_rface(
            bounded,
            scad.make_rectangle_rwire(3.0, 3.0),
        )

        self.assertAlmostEqual(trimmed.get_area(), 5.0, places=6)
        self.assertEqual(len(trimmed._iter_inner_wires()), 1)

    def test_trim_intersects_partially_overlapping_planar_loop(self):
        backing = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        carrier = scad.trim_surface_rface(
            backing,
            scad.make_rectangle_rwire(4.0, 4.0),
        )

        # 2(x) x 4(y) loop poking out on +x: same footprint the test has
        # always exercised; the dims read (4, 2) under the pre-fix transposed
        # plane basis, (2, 4) under the width-along-x convention.
        trimmed = scad.trim_surface_rface(
            carrier,
            scad.make_rectangle_rwire(2.0, 4.0, center=(1.5, 0.0, 0.0)),
        )

        self.assertAlmostEqual(trimmed.get_area(), 6.0, places=6)

    def test_trim_rejects_empty_and_disconnected_carrier_intersections(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-4, -4, 0), (-4, 4, 0)], [(4, -4, 0), (4, 4, 0)]]
        )
        bounded = scad.trim_surface_rface(
            carrier,
            scad.make_rectangle_rwire(6.0, 6.0),
            holes=[scad.make_rectangle_rwire(2.0, 4.0)],
        )

        with self.assertRaisesRegex(
            scad.SimpleCADError,
            "exactly one connected Face; intersection is empty",
        ):
            scad.trim_surface_rface(bounded, scad.make_rectangle_rwire(1.0, 1.0))
        with self.assertRaisesRegex(
            scad.SimpleCADError,
            "exactly one connected Face; intersection produced 2 disconnected Faces",
        ):
            scad.trim_surface_rface(bounded, scad.make_rectangle_rwire(4.0, 2.0))

    def test_trim_accepts_closed_near_tolerance_oscillating_loop(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        tolerance = 1.0e-6
        outer = scad.make_interpolated_spline_rwire(
            points=[
                (
                    2.0 * math.cos(2.0 * math.pi * index / 64.0),
                    2.0 * math.sin(2.0 * math.pi * index / 64.0),
                    0.75 * tolerance * math.sin(16.0 * math.pi * index / 32.0),
                )
                for index in range(64)
            ],
            periodic=True,
            tolerance=1.0e-9,
        )

        trimmed = scad.trim_surface_rface(carrier, outer, tolerance=tolerance)

        self.assertIsInstance(trimmed, scad.Face)
        self.assertEqual(len(trimmed._iter_wires()), 1)

    def test_trim_rejects_closed_oscillating_curve_between_coarse_samples(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        outer = scad.make_interpolated_spline_rwire(
            points=[
                (
                    2.0 * math.cos(2.0 * math.pi * index / 64.0),
                    2.0 * math.sin(2.0 * math.pi * index / 64.0),
                    0.5 if index % 2 else 0.0,
                )
                for index in range(64)
            ],
            periodic=True,
            tolerance=1.0e-9,
        )

        with self.assertRaisesRegex(scad.SimpleCADError, "deviates from the carrier"):
            scad.trim_surface_rface(carrier, outer, tolerance=1.0e-9)

    def test_trim_rejects_open_and_self_intersecting_boundaries(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        open_wire = self._line_wire((-1.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self_intersecting = scad.make_polyline_rwire(
            [
                (-2.0, -2.0, 0.0),
                (2.0, 2.0, 0.0),
                (-2.0, 2.0, 0.0),
                (2.0, -2.0, 0.0),
            ],
            closed=True,
        )

        with self.assertRaisesRegex(scad.SimpleCADError, "must be closed"):
            scad.trim_surface_rface(carrier, open_wire)
        with self.assertRaisesRegex(scad.SimpleCADError, "must be simple"):
            scad.trim_surface_rface(carrier, self_intersecting)

    def test_trim_surface_rejects_off_carrier_wire(self):
        carrier = scad.make_bezier_surface_rface(
            [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
        )
        outer = scad.make_rectangle_rwire(4.0, 4.0, center=(0, 0, 1))

        with self.assertRaisesRegex(scad.SimpleCADError, "trim"):
            scad.trim_surface_rface(carrier, outer)

    def test_shell_loft_roles_names_point_profiles_and_replay(self):
        with scad.GraphSession() as session:
            lower = scad.make_circle_rwire((0, 0, 0), 2.0)
            upper = scad.make_circle_rwire((0, 0, 2), 1.0)
            open_shell = scad.loft_rshell(
                [lower, upper],
                tag_prefix="skin",
                result_tag="part.skin",
                start_wire_tag="anchor.inlet",
                end_wire_tag="anchor.outlet",
                side_faces_tag="group.side",
            )
            session.capture_result(value=open_shell)

        replayed = scad.replay_model_json(scad.export_model_json(session), strict=True)[
            0
        ]
        self.assertIsInstance(replayed, scad.Shell)
        self.assertFalse(replayed.is_closed())
        self.assertEqual(len(replayed._iter_wires()), 2)
        self.assertEqual(
            len(scad.ql.wires().where(scad.ql.tag("anchor.inlet")).resolve(replayed)),
            1,
        )
        self.assertEqual(
            len(scad.ql.wires().where(scad.ql.tag("anchor.outlet")).resolve(replayed)),
            1,
        )
        self.assertEqual(
            len(scad.ql.faces().where(scad.ql.tag("group.side")).resolve(replayed)),
            1,
        )
        self.assertIn("part.skin", scad.list_tags(replayed))
        self.assertIn("skin.shell", scad.list_tags(replayed))

        point = scad.make_point_rvertex(0, 0, 4)
        pointed = scad.loft_rshell([upper, point], start_wire_tag="anchor.base")
        self.assertEqual(len(pointed._iter_wires()), 1)
        self.assertEqual(
            len(scad.ql.wires().where(scad.ql.tag("anchor.base")).resolve(pointed)),
            1,
        )

    def test_sew_and_free_boundary_multi_output_replay(self):
        with scad.GraphSession() as session:
            face = scad.make_bezier_surface_rface(
                [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]]
            )
            shell = scad.sew_faces_rshell([face])
            boundaries = scad.free_boundaries_rwirelist(shell)
            session.capture_result(value=boundaries)

        replayed = scad.replay_model_json(scad.export_model_json(session))
        self.assertEqual(len(boundaries), 1)
        self.assertEqual(len(replayed), 1)
        original_length = sum(edge.get_length() for edge in boundaries[0]._iter_edges())
        replayed_length = sum(edge.get_length() for edge in replayed[0]._iter_edges())
        self.assertAlmostEqual(replayed_length, original_length, places=8)

    def test_sew_shell_faces_replays_selected_face_inputs(self):
        with scad.GraphSession() as session:
            lower = scad.make_circle_rwire((0, 0, 0), 1.0)
            upper = scad.make_circle_rwire((0, 0, 2), 1.0)
            lofted = scad.loft_rshell([lower, upper])
            resewn = scad.sew_faces_rshell(lofted._iter_faces())
            session.capture_result(value=resewn)

        payload = scad.export_model_json(session)
        sew_node = next(
            node
            for node in json.loads(payload)["graph"]["nodes"]
            if node["op"] == "sew_faces_rshell"
        )
        self.assertEqual(len(sew_node["params"]["input_refs"]), 1)

        replayed = scad.replay_model_json(payload, strict=True)
        self.assertEqual(len(replayed), 1)
        self.assertIsInstance(replayed[0], scad.Shell)
        self.assertEqual(len(replayed[0]._iter_faces()), len(resewn._iter_faces()))
        self.assertAlmostEqual(replayed[0].get_area(), resewn.get_area(), places=8)

    def test_solidification_does_not_overwrite_existing_shell_face_refs(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 2.0, 3.0)
            shell = scad.sew_faces_rshell(box._iter_faces())
            retained_face = shell.get_faces(0)
            retained_ref = retained_face._get_runtime("topo.ref")
            scad.make_solid_from_shell_rsolid(shell)
            moved = scad.translate_shape(retained_face, (1.0, 0.0, 0.0))
            session.capture_result(value=moved)

        self.assertEqual(retained_face._get_runtime("topo.ref"), retained_ref)
        replayed = scad.replay_model_json(scad.export_model_json(session), strict=True)
        self.assertEqual(len(replayed), 1)
        self.assertIsInstance(replayed[0], scad.Face)

    def test_solidification_isolates_cache_and_preserves_subshape_state(self):
        box = scad.make_box_rsolid(1.0, 2.0, 3.0)
        shell = scad.sew_faces_rshell(box._iter_faces())
        source_face = shell.get_faces(0)
        scad.apply_tag(source_face, "role.shell_face_state")
        source_face.set_metadata("audit", {"value": 1})
        source_face._set_runtime("audit.runtime", {"value": 2})

        solid = scad.make_solid_from_shell_rsolid(shell)
        matches = [
            face
            for face in solid._iter_faces()
            if face.wrapped.IsSame(source_face.wrapped)
        ]

        self.assertIsNot(shell._topology_cache, solid._topology_cache)
        self.assertEqual(len(matches), 1)
        self.assertIn("role.shell_face_state", scad.list_tags(matches[0]))
        self.assertEqual(matches[0].get_metadata("audit"), {"value": 1})
        self.assertEqual(matches[0]._get_runtime("audit.runtime"), {"value": 2})

    def test_solid_subshape_uses_fresh_graph_references(self):
        with scad.GraphSession() as session:
            box = scad.make_box_rsolid(1.0, 2.0, 3.0)
            shell = scad.sew_faces_rshell(box._iter_faces())
            solid = scad.make_solid_from_shell_rsolid(shell)
            moved = scad.translate_shape(solid.get_faces(0), (1.0, 0.0, 0.0))
            session.capture_result(value=moved)

        replayed = scad.replay_model_json(scad.export_model_json(session), strict=True)
        self.assertEqual(len(replayed), 1)
        self.assertIsInstance(replayed[0], scad.Face)

    def test_partial_trim_lineage_stays_partial_after_transform(self):
        carrier = scad.apply_tag(
            scad.make_bezier_surface_rface(
                [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
            ),
            "role.trim_carrier",
        )
        trimmed = scad.trim_surface_rface(
            carrier,
            scad.make_rectangle_rwire(4.0, 4.0),
        )

        moved = scad.translate_shape(trimmed, (1.0, 0.0, 0.0))

        self.assertEqual(moved._get_runtime("semantic.lineage.coverage"), "partial")
        self.assertEqual(
            [witness.binding.tag for witness in moved._tag_lineage],
            ["role.trim_carrier"],
        )
        self.assertEqual(moved._tag_lineage[0].source_topo_id, trimmed.topo_id)
        self.assertTrue(
            all(witness.coverage == "partial" for witness in moved._tag_lineage)
        )

    def test_continuation_only_lineage_does_not_cross_a_trim_fragment(self):
        carrier = scad.apply_tag_rselection(
            scad.make_bezier_surface_rface(
                [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
            ),
            scad.ql.faces().exactly(1),
            "role.continuation_only",
            lineage_policy="continuation",
        )
        moved = scad.translate_shape(carrier, (0.0, 0.0, 0.0))

        trimmed = scad.trim_surface_rface(
            moved,
            scad.make_rectangle_rwire(4.0, 4.0),
        )

        self.assertNotIn(
            "role.continuation_only",
            [witness.binding.tag for witness in trimmed._tag_lineage],
        )

    def test_cylindrical_tolerance_expression_replays_as_a_parameter(self):
        with scad.GraphSession() as session:
            tolerance = scad.var("surface_tol", 1.0e-6, unit="mm")
            carrier = scad.make_cylindrical_surface_rface(
                2.0,
                (0.0, math.pi),
                (0.0, 2.0),
                tolerance=tolerance,
            )
            session.capture_result(value=carrier)

        payload = json.loads(scad.export_model_json(session))
        node = next(
            item
            for item in payload["graph"]["nodes"]
            if item["op"] == "make_cylindrical_surface_rface"
        )
        self.assertIn("tolerance", node["param_exprs"])
        replayed = scad.replay_model_json(json.dumps(payload), strict=True)
        self.assertEqual(len(replayed), 1)

    def test_lineage_none_coverage_is_not_overwritten(self):
        carrier = scad.apply_tag(
            scad.make_bezier_surface_rface(
                [[(-3, -3, 0), (-3, 3, 0)], [(3, -3, 0), (3, 3, 0)]]
            ),
            "role.source",
        )
        carrier._set_runtime("semantic.lineage.coverage", "none")

        trimmed = scad.trim_surface_rface(
            carrier,
            scad.make_rectangle_rwire(4.0, 4.0),
        )

        self.assertEqual(trimmed._get_runtime("semantic.lineage.coverage"), "none")
        self.assertEqual(len(trimmed._tag_lineage), 1)
        self.assertEqual(trimmed._tag_lineage[0].coverage, "none")

    def test_closed_shell_free_boundaries_records_zero_outputs(self):
        with scad.GraphSession() as session:
            lower = scad.make_circle_rwire((0, 0, 0), 1.0)
            upper = scad.make_circle_rwire((0, 0, 2), 1.0)
            closed_shell = scad.fill_holes_rshell(scad.loft_rshell([lower, upper]))
            boundaries = scad.free_boundaries_rwirelist(closed_shell)

        node = session.graph.leaf_nodes()[0]
        self.assertEqual(boundaries, [])
        self.assertEqual(node.op, "free_boundaries_rwirelist")
        self.assertEqual(node.output_count, 0)
        self.assertEqual(scad.replay_model_json(scad.export_model_json(session)), [])

    def test_loft_rejects_middle_points_and_missing_endpoint_topology(self):
        lower = scad.make_circle_rwire((0, 0, 0), 2.0)
        middle = scad.make_point_rvertex(0, 0, 2)
        upper = scad.make_circle_rwire((0, 0, 4), 1.0)

        with self.assertRaisesRegex(scad.SimpleCADError, "only at the start or end"):
            scad.loft_rshell([lower, middle, upper])
        with self.assertRaisesRegex(scad.SimpleCADError, "end_wire_tag requires"):
            scad.loft_rshell([lower, middle], end_wire_tag="anchor.end")
        with self.assertRaisesRegex(scad.SimpleCADError, "end_face_tag requires"):
            scad.loft_rsolid([lower, middle], end_face_tag="anchor.end")

    def test_strict_replay_rejects_ordered_input_ref_tampering(self):
        with scad.GraphSession() as session:
            edge_a = scad.make_line_redge((0, 0, 0), (1, 0, 0))
            edge_b = scad.make_line_redge((0, 0, 1), (1, 0, 1))
            scad.make_ruled_surface_rface(edge_a, edge_b)

        payload = json.loads(scad.export_model_json(session))
        damaged = deepcopy(payload)
        ruled_node = next(
            node
            for node in damaged["graph"]["nodes"]
            if node["op"] == "make_ruled_surface_rface"
        )
        ruled_node["params"]["input_refs"][0]["output_slot"] = 99

        with self.assertRaisesRegex(scad.SimpleCADError, "missing output slot 99"):
            scad.replay_model_json(json.dumps(damaged), strict=True)

    def test_invalid_surface_inputs_use_public_error_contract(self):
        with self.assertRaisesRegex(scad.SimpleCADError, "rectangular finite grid"):
            scad.make_bezier_surface_rface([[(0, 0, 0)]])
        with self.assertRaisesRegex(scad.SimpleCADError, "positive tolerance"):
            scad.fit_point_grid_rface(
                [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]],
                tolerance=0.0,
            )


if __name__ == "__main__":
    unittest.main()
