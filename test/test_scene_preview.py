"""The preview: a product's geometry straight from its solids, for a viewer under edit."""

from __future__ import annotations

import json
import math
import struct
import unittest

import numpy as np

import simplecadapi as scad
from simplecadapi.scene import preview as pv


def box_part(part_id: str, size=(10.0, 20.0, 30.0)) -> scad.Part:
    return scad.Part(part_id=part_id, body=scad.make_box_rsolid(*size))


class PreviewGeometryTest(unittest.TestCase):
    def setUp(self) -> None:
        pv.clear_preview_cache()

    def test_a_part_previews_with_groups_that_tile_the_triangles(self) -> None:
        scene = pv.compile_preview(box_part("box"))
        (part,) = scene.parts.values()
        self.assertEqual(part.triangle_count, 12)  # two per face
        self.assertEqual(len(part.face_groups), 6)
        self.assertEqual(sum(count for _, _, count in part.face_groups), len(part.indices))
        self.assertEqual(len(part.edge_groups), 12)
        self.assertEqual(len(part.vertex_ids), 8)
        self.assertEqual([n.node_id for n in scene.nodes], ["node/box"])
        positions = part.positions.astype(np.float64) * 1000.0  # glTF metres -> mm (x, z, -y)
        self.assertAlmostEqual(float(positions[:, 0].max() - positions[:, 0].min()), 10.0, places=3)
        self.assertAlmostEqual(float(positions[:, 2].max() - positions[:, 2].min()), 20.0, places=3)  # glTF z is -y
        self.assertAlmostEqual(float(positions[:, 1].max() - positions[:, 1].min()), 30.0, places=3)  # glTF y is z

    def test_triangle_areas_add_up_to_the_surface(self) -> None:
        part = box_part("box")
        (preview,) = pv.compile_preview(part).parts.values()
        total = 0.0
        for _, first, count in preview.face_groups:
            tri = preview.indices[first : first + count].reshape(-1, 3)
            a, b, c = (preview.positions[tri[:, k]].astype(np.float64) * 1000.0 for k in range(3))
            total += 0.5 * float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
        self.assertAlmostEqual(total, 2 * (10 * 20 + 10 * 30 + 20 * 30), places=2)

    def test_the_same_content_is_remembered_even_when_the_object_is_rebuilt(self) -> None:
        first = pv.compile_preview(box_part("a"))
        second = pv.compile_preview(box_part("b"))  # another object, the same box
        self.assertIs(next(iter(first.parts.values())), next(iter(second.parts.values())))
        other = pv.compile_preview(box_part("c", (11.0, 20.0, 30.0)))
        self.assertIsNot(next(iter(first.parts.values())), next(iter(other.parts.values())))

    def test_a_tolerance_is_part_of_the_key(self) -> None:
        part = scad.Part(part_id="cyl", body=scad.make_cylinder_rsolid(5.0, 10.0))
        fine = next(iter(pv.compile_preview(part, linear_tolerance=0.01, angular_tolerance=0.05).parts.values()))
        coarse = next(iter(pv.compile_preview(part, linear_tolerance=0.5, angular_tolerance=0.5).parts.values()))
        self.assertGreater(fine.triangle_count, coarse.triangle_count)


class PreviewAssemblyTest(unittest.TestCase):
    def setUp(self) -> None:
        pv.clear_preview_cache()

    def nested(self) -> scad.Assembly:
        leaf = scad.make_assembly_rassembly(assembly_id="leaf")
        leaf = scad.add_component_rassembly(
            assembly=leaf, item=box_part("pin", (2.0, 2.0, 8.0)), component_id="pin",
            placement=scad.make_placement_rplacement(origin=(5.0, 0.0, 0.0)),
        )
        top = scad.make_assembly_rassembly(assembly_id="top")
        top = scad.add_component_rassembly(
            assembly=top, item=box_part("base"), component_id="base",
            placement=scad.identity_placement_rplacement(),
        )
        # rotated 90 degrees about z, then moved: x -> y
        return scad.add_component_rassembly(
            assembly=top, item=leaf, component_id="arm",
            placement=scad.make_placement_rplacement(origin=(100.0, 0.0, 0.0), x_axis=(0.0, 1.0, 0.0), y_axis=(-1.0, 0.0, 0.0)),
        )

    def test_nested_placements_are_composed_and_parts_are_not_repeated(self) -> None:
        asm = self.nested()
        asm = scad.add_component_rassembly(
            assembly=asm, item=box_part("pin", (2.0, 2.0, 8.0)), component_id="spare",
            placement=scad.make_placement_rplacement(origin=(0.0, 50.0, 0.0)),
        )
        scene = pv.compile_preview(asm)
        by_id = {n.node_id: n for n in scene.nodes}
        self.assertEqual(sorted(by_id), ["node/top/arm/pin", "node/top/base", "node/top/spare"])
        pin = by_id["node/top/arm/pin"].placement
        # the pin sits at x=5 in the arm; the arm is turned x -> y and moved to x=100
        self.assertTrue(np.allclose(pin.origin, (100.0, 5.0, 0.0)))
        self.assertTrue(np.allclose(pin.x_axis, (0.0, 1.0, 0.0)))
        self.assertEqual(len(scene.parts), 2)  # "pin" is one geometry, two instances
        self.assertEqual(by_id["node/top/arm/pin"].part_key, by_id["node/top/spare"].part_key)

    def test_an_empty_assembly_cannot_be_previewed(self) -> None:
        with self.assertRaises(pv.PreviewError):
            pv.compile_preview(scad.make_assembly_rassembly(assembly_id="none"))


class PreviewWireTest(unittest.TestCase):
    def test_the_encoding_round_trips_through_its_header(self) -> None:
        scene = pv.compile_preview(box_part("box"))
        data = pv.encode_preview(scene)
        self.assertTrue(data.startswith(pv.MAGIC))
        header = pv.decode_preview_header(data)
        self.assertEqual(header["schema"], pv.PREVIEW_SCHEMA)
        (part,) = header["parts"]
        (length,) = struct.unpack_from("<I", data, len(pv.MAGIC))
        base = len(pv.MAGIC) + 8 + length
        positions = np.frombuffer(data, dtype="<f4", count=part["positions"]["count"], offset=base + part["positions"]["offset"])
        (scene_part,) = scene.parts.values()
        self.assertTrue(np.array_equal(positions.reshape(-1, 3), scene_part.positions))
        indices = np.frombuffer(data, dtype="<u4", count=part["indices"]["count"], offset=base + part["indices"]["offset"])
        self.assertTrue(np.array_equal(indices, scene_part.indices))
        self.assertTrue(all(g["entity_id"].startswith("entity/box/face/") for g in part["face_groups"]))
        self.assertEqual(part["solid_entity_id"].split("/")[:3], ["entity", "box", "solid"])
        self.assertEqual(header["nodes"][0]["node_id"], "node/box")
        with self.assertRaises(pv.PreviewError):
            pv.decode_preview_header(b"nonsense")


class EntityInfoTest(unittest.TestCase):
    def setUp(self) -> None:
        pv.clear_preview_cache()
        self.scene = pv.compile_preview(box_part("box"))
        (self.part,) = self.scene.parts.values()

    def test_a_face_reports_what_the_package_sidecar_would(self) -> None:
        topo, _, _ = self.part.face_groups[0]
        info = pv.entity_info(self.scene, f"entity/box/face/{topo}")
        assert info is not None
        self.assertEqual(info["kind"], "face")
        self.assertEqual(info["geometry"]["type"], "plane")
        self.assertIn(round(info["properties"]["area"], 6), (200.0, 300.0, 600.0))
        self.assertEqual(len(info["properties"]["centroid"]), 3)

    def test_an_edge_a_vertex_and_the_solid(self) -> None:
        edge = pv.entity_info(self.scene, f"entity/box/edge/{self.part.edge_groups[0][0]}")
        assert edge is not None
        self.assertEqual(edge["geometry"]["type"], "line")
        self.assertIn(round(edge["properties"]["length"], 6), (10.0, 20.0, 30.0))
        vertex = pv.entity_info(self.scene, f"entity/box/vertex/{self.part.vertex_ids[0]}")
        assert vertex is not None
        self.assertEqual(vertex["geometry"]["type"], "point")
        solid = pv.entity_info(self.scene, f"entity/box/solid/{self.part.solid_topo_id}")
        assert solid is not None
        self.assertTrue(math.isclose(solid["properties"]["volume"], 6000.0, rel_tol=1e-9))

    def test_unknown_entities_have_no_info(self) -> None:
        self.assertIsNone(pv.entity_info(self.scene, "entity/box/face/face_999"))
        self.assertIsNone(pv.entity_info(self.scene, "entity/other/face/face_0"))
        self.assertIsNone(pv.entity_info(self.scene, "entity/box/gadget/x"))


if __name__ == "__main__":
    unittest.main()


class AgainstThePackageTest(unittest.TestCase):
    """The preview names and describes entities exactly as the package's sidecar does."""

    def test_a_real_part_has_the_packages_entity_ids_and_properties(self) -> None:
        import io
        import zipfile
        from pathlib import Path

        from simplecadapi.product.packages import build_product_package, encode_product_package
        from simplecadapi.runtime import run_notebook

        run = run_notebook(Path(__file__).resolve().parents[1] / "examples" / "flange_plate" / "flange_plate.py")
        scene = pv.compile_preview(run.product)
        archive = zipfile.ZipFile(io.BytesIO(encode_product_package(build_product_package(run.definition, validate=False))))
        sidecar = None
        for name in archive.namelist():
            blob = archive.read(name)
            if blob[:1] == b"{" and b'"face_groups"' in blob:
                sidecar = json.loads(blob)
        assert sidecar is not None
        reference = {e["entity_id"]: e for e in sidecar["entities"]}
        header = pv.decode_preview_header(pv.encode_preview(scene))
        (part,) = header["parts"]
        mine = (
            {g["entity_id"] for g in part["face_groups"]}
            | {g["entity_id"] for g in part["edge_groups"]}
            | set(part["vertex_ids"])
            | {part["solid_entity_id"]}
        )
        self.assertEqual(mine, set(reference))

        def close(x, y) -> bool:
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-6)
            if isinstance(x, dict) and isinstance(y, dict):
                return x.keys() == y.keys() and all(close(x[k], y[k]) for k in x)
            if isinstance(x, list) and isinstance(y, list):
                return len(x) == len(y) and all(close(p, q) for p, q in zip(x, y))
            return x == y

        for entity_id in sorted(mine)[::5]:
            info = pv.entity_info(scene, entity_id)
            assert info is not None, entity_id
            for field in ("properties", "geometry", "tags"):
                self.assertTrue(close(info[field], reference[entity_id][field]), (entity_id, field))
