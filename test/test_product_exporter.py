"""End-to-end tests for product-package CAD and mesh exporters."""

from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import unittest

import numpy as np
import trimesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.StepRepr import StepRepr_DescriptiveRepresentationItem
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFPrs import XCAFPrs_DocumentExplorer

import simplecadapi as scad
from simplecadapi.inspect.brep.render import _load_step_xcaf


def _label_name(label) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _read_occurrences(path: Path) -> list[dict[str, object]]:
    XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetPropsMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(document):
        raise AssertionError(f"could not read exported STEP file {path}")
    explorer = XCAFPrs_DocumentExplorer(document, 0)
    records: list[dict[str, object]] = []
    while explorer.More():
        node = explorer.Current()
        translation = node.Location.Transformation().TranslationPart()
        records.append(
            {
                "depth": int(explorer.CurrentDepth()),
                "name": _label_name(node.Label) or _label_name(node.RefLabel),
                "ref_name": _label_name(node.RefLabel),
                "assembly": bool(node.IsAssembly),
                "xyz": [
                    round(float(translation.X()), 3),
                    round(float(translation.Y()), 3),
                    round(float(translation.Z()), 3),
                ],
            }
        )
        explorer.Next()
    return records


def _read_simplecad_metadata(path: Path) -> dict[str, dict[str, object]]:
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise AssertionError(f"could not read exported STEP file {path}")
    model = reader.ChangeReader().WS().Model()
    records: dict[str, dict[str, object]] = {}
    for index in range(1, model.NbEntities() + 1):
        entity = model.Entity(index)
        if not isinstance(entity, StepRepr_DescriptiveRepresentationItem):
            continue
        name = entity.Name().ToCString()
        if not name.startswith("SimpleCAD:"):
            continue
        records[name] = json.loads(entity.Description().ToCString())
    return records


def _build_nested_package():
    @scad.part(id="linked", project_root=Path(__file__).parent)
    def build_part() -> scad.Part:
        body = scad.make_box_rsolid(1.0, 2.0, 3.0)
        face = scad.apply_tag(body.get_faces(0), "interface.mount_face")
        part = scad.make_part_rpart("linked", body, name="Part linked")
        return scad.add_connector_rpart(
            part,
            scad.make_face_connector_rconnector("mount", face),
        )

    part = build_part()

    @scad.assemble(
        id="child",
        definitions=(part,),
        project_root=Path(__file__).parent,
    )
    def build_child() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly("child", name="Child assembly")
        for component_id, name in (
            ("inner_a", "Inner linked part A"),
            ("inner_b", "Inner linked part B"),
        ):
            assembly = scad.add_component_rassembly(
                assembly,
                part.value,
                component_id=component_id,
                placement=scad.identity_placement_rplacement(),
                name=name,
            )
        assembly = scad.ground_component_rassembly(assembly, "inner_a")
        assembly = scad.add_revolute_constraint_rassembly(
            assembly,
            "joint",
            scad.make_connector_ref_rconnectorref("inner_a", "mount"),
            scad.make_connector_ref_rconnectorref("inner_b", "mount"),
            drive_angle_degrees=15.0,
        )
        return scad.solve_assembly_constraints_rassembly(assembly)

    child = build_child()

    @scad.assemble(
        id="root",
        definitions=(child, part),
        project_root=Path(__file__).parent,
    )
    def build_root() -> scad.Assembly:
        assembly = scad.make_assembly_rassembly("root", name="Root assembly")
        assembly = scad.add_component_rassembly(
            assembly,
            child.value,
            component_id="nested",
            placement=scad.make_placement_rplacement(origin=(10.0, 0.0, 0.0)),
            name="Nested child assembly",
        )
        return scad.add_component_rassembly(
            assembly,
            part.value,
            component_id="direct",
            placement=scad.make_placement_rplacement(origin=(0.0, 5.0, 0.0)),
            name="Direct linked part",
        )

    return scad.build_product_package(build_root())


def _build_cylinder_package():
    @scad.part(
        id="cylinder",
        project_root=Path(__file__).parent,
    )
    def build_cylinder() -> scad.Part:
        body = scad.make_cylinder_rsolid(radius=4.0, height=8.0)
        return scad.make_part_rpart("cylinder", body)

    return scad.build_product_package(build_cylinder())


class TestProductExporter(unittest.TestCase):
    def test_exporters_are_available_only_from_exporter_namespace(self):
        self.assertIs(
            scad.exporter.export_product_package_to_step,
            scad.exporter.step.export_product_package_to_step,
        )
        self.assertIs(
            scad.exporter.export_product_package_to_obj,
            scad.exporter.obj.export_product_package_to_obj,
        )
        self.assertIs(
            scad.exporter.export_product_package_to_stl,
            scad.exporter.stl.export_product_package_to_stl,
        )
        self.assertIs(
            scad.exporter.export_product_package_to_mjcf,
            scad.exporter.mjcf.export_product_package_to_mjcf,
        )
        self.assertFalse(hasattr(scad, "export_step"))
        self.assertFalse(hasattr(scad, "export_stl"))
        self.assertFalse(hasattr(scad, "export_obj"))
        self.assertFalse(hasattr(scad.translator, "ap242_translator"))

    def test_nested_package_preserves_ap242_product_structure_and_placements(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package = _build_nested_package()
            step_path = root / "nested.step"
            report = scad.exporter.export_product_package_to_step(package, step_path)
            records = _read_occurrences(step_path)
            content = step_path.read_text(encoding="utf-8")
            metadata = _read_simplecad_metadata(step_path)

        self.assertIn("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING", content)
        self.assertEqual(report.schema, "AP242DIS")
        self.assertEqual(report.definition_ids, ("linked", "child", "root"))
        self.assertEqual(report.occurrence_count, 4)
        self.assertEqual(report.metadata_item_count, 7)
        self.assertEqual(
            set(metadata),
            {
                "SimpleCAD:definition:single_solid:linked",
                "SimpleCAD:definition:assembly:child",
                "SimpleCAD:definition:assembly:root",
                "SimpleCAD:occurrence:child:inner_a",
                "SimpleCAD:occurrence:child:inner_b",
                "SimpleCAD:occurrence:root:nested",
                "SimpleCAD:occurrence:root:direct",
            },
        )
        linked = metadata["SimpleCAD:definition:single_solid:linked"]
        self.assertEqual(linked["revision"], "1.0.0")
        self.assertRegex(str(linked["content_hash"]), r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(linked["connectors"][0]["connector_id"], "mount")
        child = metadata["SimpleCAD:definition:assembly:child"]
        self.assertEqual(child["grounded_component_ids"], ["inner_a"])
        self.assertEqual(child["constraints"][0]["constraint_id"], "joint")
        self.assertEqual(child["constraints"][0]["drive_angle_degrees"], 15.0)
        nested = metadata["SimpleCAD:occurrence:root:nested"]
        self.assertEqual(nested["definition_id"], "child")
        self.assertEqual(nested["placement"]["origin"], [10.0, 0.0, 0.0])
        self.assertEqual(
            records,
            [
                {
                    "depth": 0,
                    "name": "Root assembly",
                    "ref_name": "Root assembly",
                    "assembly": True,
                    "xyz": [0.0, 0.0, 0.0],
                },
                {
                    "depth": 1,
                    "name": "Direct linked part",
                    "ref_name": "Part linked",
                    "assembly": False,
                    "xyz": [0.0, 5.0, 0.0],
                },
                {
                    "depth": 1,
                    "name": "Nested child assembly",
                    "ref_name": "Child assembly",
                    "assembly": True,
                    "xyz": [10.0, 0.0, 0.0],
                },
                {
                    "depth": 2,
                    "name": "Inner linked part A",
                    "ref_name": "Part linked",
                    "assembly": False,
                    "xyz": [10.0, 0.0, 0.0],
                },
                {
                    "depth": 2,
                    "name": "Inner linked part B",
                    "ref_name": "Part linked",
                    "assembly": False,
                    "xyz": [10.0, -0.388, 0.051],
                },
            ],
        )
        self.assertTrue(any("feature history" in item for item in report.limitations))
        self.assertFalse(any("OCAF comments" in item for item in report.limitations))

    def test_part_material_and_color_enter_stepcaf_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            @scad.part(
                id="colored",
                project_root=Path(__file__).parent,
            )
            def build_colored() -> scad.Part:
                body = scad.make_box_rsolid(1.0, 2.0, 3.0)
                part = scad.make_part_rpart("colored", body, name="Colored part")
                material = scad.make_material_rmaterial(
                    "blue_aluminum",
                    name="Blue aluminum",
                    density=2.7e-6,
                    density_unit="kg/mm^3",
                    color=(0.2, 0.4, 0.6),
                )
                return scad.assign_material_rpart(part, material)

            package = scad.build_product_package(build_colored())
            step_path = root / "colored.step"
            report = scad.exporter.export_product_package_to_step(package, step_path)
            content = step_path.read_text(encoding="utf-8")
            _shape, face_colors = _load_step_xcaf(step_path)

        self.assertEqual(report.material_ids, ("blue_aluminum",))
        self.assertIn(
            "PROPERTY_DEFINITION('material property','material name'", content
        )
        self.assertIn("MEASURE_REPRESENTATION_ITEM('kg/mm^3',2.7E-06", content)
        self.assertIn('"material_id": "blue_aluminum"', content)
        self.assertTrue(face_colors)
        self.assertEqual(
            {
                tuple(round(value, 3) for value in color[:3])
                for color in face_colors.values()
            },
            {(0.2, 0.4, 0.6)},
        )

    def test_nested_package_exports_matching_direct_brep_meshes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package = _build_nested_package()
            stl_path = root / "nested.stl"
            obj_path = root / "nested.obj"
            stl_report = scad.exporter.export_product_package_to_stl(
                package,
                stl_path,
                linear_deflection=0.05,
                angular_deflection_degrees=10.0,
            )
            obj_report = scad.exporter.export_product_package_to_obj(
                package,
                obj_path,
                linear_deflection=0.05,
                angular_deflection_degrees=10.0,
            )
            stl_mesh = trimesh.load_mesh(stl_path, force="mesh", process=False)
            obj_mesh = trimesh.load_mesh(obj_path, force="mesh", process=False)
            stl_processed = trimesh.load_mesh(stl_path, force="mesh", process=True)
            obj_lines = obj_path.read_text(encoding="ascii").splitlines()
            stl_size = stl_path.stat().st_size

        source_bounds = np.asarray(
            [
                [-0.5, -1.35415439394285, -0.2077077845361233],
                [10.5, 6.0, 3.207707784536123],
            ]
        )
        for report in (stl_report, obj_report):
            self.assertEqual(report.root_definition_id, "root")
            self.assertEqual(report.definition_count, 3)
            self.assertEqual(report.solid_count, 3)
            self.assertGreater(report.vertex_count, 0)
            self.assertGreater(report.triangle_count, 0)
            self.assertEqual(report.linear_deflection, 0.05)
            self.assertEqual(report.angular_deflection_degrees, 10.0)
            self.assertFalse(report.relative)
            self.assertEqual(
                report.tessellation_backend,
                "opencascade-brep-tessellation",
            )
        self.assertEqual(stl_report.vertex_count, obj_report.vertex_count)
        self.assertEqual(stl_report.triangle_count, obj_report.triangle_count)
        self.assertEqual(len(stl_mesh.faces), stl_report.triangle_count)
        self.assertEqual(len(obj_mesh.faces), obj_report.triangle_count)
        self.assertEqual(
            sum(line.startswith("f ") for line in obj_lines),
            obj_report.triangle_count,
        )
        self.assertTrue(
            all(len(line.split()) == 4 for line in obj_lines if line.startswith("f "))
        )
        self.assertTrue(np.allclose(stl_mesh.bounds, source_bounds, atol=1.0e-6))
        self.assertTrue(np.allclose(obj_mesh.bounds, source_bounds, atol=1.0e-6))
        self.assertTrue(stl_processed.is_watertight)
        self.assertTrue(obj_mesh.is_watertight)
        self.assertTrue(stl_processed.is_winding_consistent)
        self.assertTrue(obj_mesh.is_winding_consistent)
        self.assertEqual(stl_size, 84 + 50 * stl_report.triangle_count)

    def test_smaller_deflection_refines_curved_brep(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package = _build_cylinder_package()
            coarse_path = root / "cylinder-coarse.obj"
            fine_path = root / "cylinder-fine.obj"
            coarse = scad.exporter.export_product_package_to_obj(
                package,
                coarse_path,
                linear_deflection=0.5,
                angular_deflection_degrees=30.0,
            )
            fine = scad.exporter.export_product_package_to_obj(
                package,
                fine_path,
                linear_deflection=0.01,
                angular_deflection_degrees=5.0,
            )
            mesh = trimesh.load_mesh(fine_path, force="mesh", process=False)

        self.assertEqual(coarse.solid_count, 1)
        self.assertEqual(fine.solid_count, 1)
        self.assertGreater(fine.vertex_count, coarse.vertex_count)
        self.assertGreater(fine.triangle_count, coarse.triangle_count)
        self.assertEqual(len(mesh.faces), fine.triangle_count)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        exact_bounds = np.asarray([[-4.0, -4.0, 0.0], [4.0, 4.0, 8.0]])
        self.assertTrue(np.all(mesh.bounds[0] >= exact_bounds[0] - 1.0e-9))
        self.assertTrue(np.all(mesh.bounds[1] <= exact_bounds[1] + 1.0e-9))
        self.assertLessEqual(float(np.max(np.abs(mesh.bounds - exact_bounds))), 0.01)

    def test_mjcf_exporter_builds_named_body_joint_site_and_mapping(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            material = scad.make_material_rmaterial(
                "test_aluminum",
                density=2.7e-6,
                density_unit="kg/mm^3",
            )

            def make_link(part_id: str) -> scad.Part:
                body = scad.make_cylinder_rsolid(radius=2.0, height=4.0)
                part = scad.make_part_rpart(part_id, body)
                part = scad.assign_material_rpart(part, material)
                return scad.add_connector_rpart(
                    part,
                    scad.make_placement_connector_rconnector(
                        "axis",
                        scad.identity_placement_rplacement(),
                    ),
                )

            @scad.part(id="mjcf_base", project_root=Path(__file__).parent)
            def build_base() -> scad.Part:
                return make_link("mjcf_base")

            @scad.part(id="mjcf_rotor", project_root=Path(__file__).parent)
            def build_rotor() -> scad.Part:
                return make_link("mjcf_rotor")

            base = build_base()
            rotor = build_rotor()

            @scad.assemble(
                id="mjcf_fixture",
                definitions=(base, rotor),
                project_root=Path(__file__).parent,
            )
            def build_fixture() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly("mjcf_fixture")
                assembly = scad.add_component_rassembly(
                    assembly,
                    base.part,
                    component_id="base",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.add_component_rassembly(
                    assembly,
                    rotor.part,
                    component_id="rotor",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.ground_component_rassembly(assembly, "base")
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly,
                    "rotor_axis",
                    scad.make_connector_ref_rconnectorref("base", "axis"),
                    scad.make_connector_ref_rconnectorref("rotor", "axis"),
                )
                return scad.set_public_connector_rassembly(assembly,
                "tool_axis",
                "rotor",
                "axis",)

            package = scad.build_product_package(build_fixture())
            xml_path = root / "fixture.xml"
            report = scad.exporter.export_product_package_to_mjcf(
                package,
                xml_path,
                linear_deflection=0.1,
            )
            xml_root = ET.parse(xml_path).getroot()
            mapping = json.loads(report.mapping_path.read_text(encoding="utf-8"))

        self.assertEqual(report.body_count, 1)
        self.assertEqual(report.joint_count, 1)
        self.assertEqual(report.equality_count, 0)
        self.assertEqual(report.site_count, 1)
        self.assertIsNotNone(xml_root.find('.//body[@name="body_rotor"]'))
        self.assertIsNotNone(xml_root.find('.//geom[@name="base"]'))
        self.assertIsNotNone(xml_root.find('.//geom[@name="rotor"]'))
        self.assertIsNotNone(xml_root.find('.//site[@name="tool_axis"]'))
        self.assertEqual(len(mapping["tree_joints"]), 1)
        self.assertEqual(mapping["sites"][0]["connector_id"], "tool_axis")

    def test_mjcf_exporter_works_without_scene_projection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            def make_link(part_id: str) -> scad.Part:
                body = scad.make_cylinder_rsolid(radius=2.0, height=4.0)
                part = scad.make_part_rpart(part_id, body)
                return scad.add_connector_rpart(
                    part,
                    scad.make_placement_connector_rconnector(
                        "axis",
                        scad.identity_placement_rplacement(),
                    ),
                )

            @scad.part(
                id="sceneless_base", project_root=Path(__file__).parent
            )
            def build_base() -> scad.Part:
                return make_link("sceneless_base")

            @scad.part(
                id="sceneless_rotor", project_root=Path(__file__).parent
            )
            def build_rotor() -> scad.Part:
                return make_link("sceneless_rotor")

            base = build_base()
            rotor = build_rotor()

            @scad.assemble(
                id="sceneless_arm",
                definitions=(base, rotor),
                project_root=Path(__file__).parent,
            )
            def build_arm() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly("sceneless_arm")
                assembly = scad.add_component_rassembly(
                    assembly,
                    base.part,
                    component_id="base",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.add_component_rassembly(
                    assembly,
                    rotor.part,
                    component_id="rotor",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.ground_component_rassembly(assembly, "base")
                return scad.add_revolute_constraint_rassembly(
                    assembly,
                    "spin",
                    scad.make_connector_ref_rconnectorref("base", "axis"),
                    scad.make_connector_ref_rconnectorref("rotor", "axis"),
                )

            package = scad.build_product_package(build_arm())
            sceneless = scad.build_product_package(
                package.root_definition,
                include_scene=False,
            )
            self.assertIsNone(sceneless.scene_path)

            report = scad.exporter.export_product_package_to_mjcf(
                scad.encode_product_package(sceneless),
                root / "sceneless.xml",
                default_density_kg_m3=1000.0,
            )

        self.assertEqual(report.joint_count, 1)
        self.assertEqual(report.body_count, 1)
        self.assertEqual(report.mesh_count, 2)
        self.assertEqual(report.site_count, 0)

    def test_mjcf_exporter_generates_unique_names_for_colliding_logical_ids(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            material = scad.make_material_rmaterial(
                material_id="collision_material",
                density=2.7e-6,
                density_unit="kg/mm^3",
            )

            def make_link(part_id: str, width: float) -> scad.Part:
                body = scad.make_box_rsolid(
                    width=width,
                    height=1.0,
                    depth=1.0,
                )
                part = scad.make_part_rpart(part_id=part_id, body=body)
                part = scad.assign_material_rpart(part=part, material=material)
                return scad.add_connector_rpart(
                    part=part,
                    connector=scad.make_placement_connector_rconnector(
                        connector_id="axis",
                        placement=scad.identity_placement_rplacement(),
                    ),
                )

            @scad.part(
                id="mjcf_base",
                project_root=Path(__file__).parent,
            )
            def build_base() -> scad.Part:
                return make_link("mjcf_base", 1.0)

            @scad.part(
                id="mjcf-link-a",
                project_root=Path(__file__).parent,
            )
            def build_first_link() -> scad.Part:
                return make_link("mjcf-link-a", 2.0)

            @scad.part(
                id="mjcf.link.a",
                project_root=Path(__file__).parent,
            )
            def build_second_link() -> scad.Part:
                return make_link("mjcf.link.a", 3.0)

            base = build_base()
            first = build_first_link()
            second = build_second_link()

            @scad.assemble(
                id="mjcf_name_collision",
                definitions=(base, first, second),
                project_root=Path(__file__).parent,
            )
            def build_fixture() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly(
                    assembly_id="mjcf_name_collision"
                )
                for result, component_id in (
                    (base, "base"),
                    (first, "arm-a"),
                    (second, "arm.a"),
                ):
                    assembly = scad.add_component_rassembly(
                        assembly=assembly,
                        item=result.part,
                        component_id=component_id,
                        placement=scad.identity_placement_rplacement(),
                    )
                assembly = scad.ground_component_rassembly(
                    assembly=assembly,
                    component_id="base",
                )
                for constraint_id, component_id in (
                    ("axis-a", "arm-a"),
                    ("axis.a", "arm.a"),
                ):
                    assembly = scad.add_revolute_constraint_rassembly(
                        assembly=assembly,
                        constraint_id=constraint_id,
                        connector_a=scad.make_connector_ref_rconnectorref(
                            component_id="base",
                            connector_id="axis",
                        ),
                        connector_b=scad.make_connector_ref_rconnectorref(
                            component_id=component_id,
                            connector_id="axis",
                        ),
                    )
                return assembly

            package = scad.build_product_package(build_fixture())
            report = scad.exporter.export_product_package_to_mjcf(
                data=package,
                output_path=root / "collision.xml",
            )
            xml_root = ET.parse(report.output_path).getroot()
            mapping = json.loads(report.mapping_path.read_text(encoding="utf-8"))

            names_by_element = {
                element: [
                    item.attrib["name"]
                    for item in xml_root.findall(f".//{element}")
                    if "name" in item.attrib
                ]
                for element in ("body", "joint", "geom", "mesh")
            }
            mesh_files = tuple(report.mesh_directory.glob("*.obj"))

        for element, names in names_by_element.items():
            self.assertEqual(len(names), len(set(names)), element)
        self.assertEqual(len(mesh_files), report.mesh_count)
        self.assertEqual(len(set(mapping["meshes"].values())), report.mesh_count)
        self.assertEqual(
            len({item["joint_name"] for item in mapping["tree_joints"]}),
            report.joint_count,
        )

    def test_mjcf_exporter_preserves_public_movable_attachment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            material = scad.make_material_rmaterial(
                material_id="public_material",
                density=2.7e-6,
                density_unit="kg/mm^3",
            )

            def make_link(part_id: str) -> scad.Part:
                body = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
                part = scad.make_part_rpart(part_id=part_id, body=body)
                part = scad.assign_material_rpart(part=part, material=material)
                return scad.add_connector_rpart(
                    part=part,
                    connector=scad.make_placement_connector_rconnector(
                        connector_id="axis",
                        placement=scad.identity_placement_rplacement(),
                    ),
                )

            @scad.part(
                id="public_base",
                project_root=Path(__file__).parent,
            )
            def build_base() -> scad.Part:
                return make_link("public_base")

            @scad.part(
                id="public_link",
                project_root=Path(__file__).parent,
            )
            def build_link() -> scad.Part:
                return make_link("public_link")

            base = build_base()
            link = build_link()

            @scad.assemble(
                id="public_child",
                definitions=(link,),
                project_root=Path(__file__).parent,
            )
            def build_child() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly(assembly_id="public_child")
                assembly = scad.add_component_rassembly(
                    assembly=assembly,
                    item=link.part,
                    component_id="link",
                    placement=scad.identity_placement_rplacement(),
                )
                return scad.set_public_connector_rassembly(assembly=assembly,
                public_connector_id="public_axis",
                source_component_id="link",
                source_connector_id="axis",)

            child = build_child()

            @scad.assemble(
                id="public_root",
                definitions=(base, child),
                project_root=Path(__file__).parent,
            )
            def build_fixture() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly(assembly_id="public_root")
                assembly = scad.add_component_rassembly(
                    assembly=assembly,
                    item=base.part,
                    component_id="base",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.add_component_rassembly(
                    assembly=assembly,
                    item=child.assembly,
                    component_id="child",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.ground_component_rassembly(
                    assembly=assembly,
                    component_id="base",
                )
                return scad.add_revolute_constraint_rassembly(
                    assembly=assembly,
                    constraint_id="child_attachment",
                    connector_a=scad.make_connector_ref_rconnectorref(
                        component_id="base",
                        connector_id="axis",
                    ),
                    connector_b=scad.make_connector_ref_rconnectorref(
                        component_id="child",
                        connector_id="public_axis",
                    ),
                )

            package = scad.build_product_package(build_fixture())
            report = scad.exporter.export_product_package_to_mjcf(
                data=package,
                output_path=root / "public.xml",
            )
            xml_root = ET.parse(report.output_path).getroot()
            mapping = json.loads(report.mapping_path.read_text(encoding="utf-8"))

        self.assertEqual(report.body_count, 1)
        self.assertEqual(report.joint_count, 1)
        self.assertEqual(
            {geom.attrib["mesh"] for geom in xml_root.findall(".//geom")},
            set(mapping["meshes"].values()),
        )
        self.assertEqual([edge["kind"] for edge in mapping["rigid_edges"]], ["ground"])
        self.assertEqual(len(mapping["tree_joints"]), 1)
        self.assertEqual(mapping["pruned_structure_nodes"], ["node/public_root/child"])

    def test_mjcf_coupling_uses_tree_support_for_shared_connector(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            material = scad.make_material_rmaterial(
                material_id="tree_support_material",
                density=2.7e-6,
                density_unit="kg/mm^3",
            )

            def make_link(part_id: str) -> scad.Part:
                body = scad.make_box_rsolid(width=1.0, height=1.0, depth=1.0)
                part = scad.make_part_rpart(part_id=part_id, body=body)
                part = scad.assign_material_rpart(part=part, material=material)
                return scad.add_connector_rpart(
                    part=part,
                    connector=scad.make_placement_connector_rconnector(
                        connector_id="axis",
                        placement=scad.identity_placement_rplacement(),
                    ),
                )

            @scad.part(
                id="tree_support_base",
                project_root=Path(__file__).parent,
            )
            def build_base() -> scad.Part:
                return make_link("tree_support_base")

            @scad.part(
                id="tree_support_driver",
                project_root=Path(__file__).parent,
            )
            def build_driver() -> scad.Part:
                return make_link("tree_support_driver")

            @scad.part(
                id="tree_support_follower",
                project_root=Path(__file__).parent,
            )
            def build_follower() -> scad.Part:
                return make_link("tree_support_follower")

            base = build_base()
            driver = build_driver()
            follower = build_follower()

            @scad.assemble(
                id="tree_support_fixture",
                definitions=(base, driver, follower),
                project_root=Path(__file__).parent,
            )
            def build_fixture() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly(
                    assembly_id="tree_support_fixture"
                )
                for result, component_id in (
                    (base, "base"),
                    (driver, "driver"),
                    (follower, "follower"),
                ):
                    assembly = scad.add_component_rassembly(
                        assembly=assembly,
                        item=result.part,
                        component_id=component_id,
                        placement=scad.identity_placement_rplacement(),
                    )
                assembly = scad.ground_component_rassembly(
                    assembly=assembly,
                    component_id="base",
                )
                base_axis = scad.make_connector_ref_rconnectorref("base", "axis")
                driver_axis = scad.make_connector_ref_rconnectorref(
                    "driver", "axis"
                )
                follower_axis = scad.make_connector_ref_rconnectorref(
                    "follower", "axis"
                )
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly=assembly,
                    constraint_id="driver_axis",
                    connector_a=base_axis,
                    connector_b=driver_axis,
                )
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly=assembly,
                    constraint_id="driver_axis_redundant",
                    connector_a=base_axis,
                    connector_b=driver_axis,
                )
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly=assembly,
                    constraint_id="follower_axis",
                    connector_a=base_axis,
                    connector_b=follower_axis,
                )
                return scad.add_gear_constraint_rassembly(
                    assembly=assembly,
                    constraint_id="driver_follower_mesh",
                    connector_a=driver_axis,
                    connector_b=follower_axis,
                    pitch_radius_a=2.0,
                    pitch_radius_b=3.0,
                )

            package = scad.build_product_package(build_fixture())
            report = scad.exporter.export_product_package_to_mjcf(
                data=package,
                output_path=root / "tree-support.xml",
            )
            mapping = json.loads(report.mapping_path.read_text(encoding="utf-8"))

        tree_joints = {
            item["joint_id"]: item["joint_name"] for item in mapping["tree_joints"]
        }
        equality = next(
            item
            for item in mapping["equalities"]
            if item["equality_id"].endswith("/driver_follower_mesh")
        )
        self.assertEqual(report.joint_count, 2)
        self.assertEqual(report.equality_count, 1)
        self.assertEqual(
            [item["joint_id"] for item in mapping["closures"]],
            ["joint/tree_support_fixture/driver_axis_redundant"],
        )
        self.assertEqual(report.closure_count, 1)
        self.assertEqual(
            equality["coefficients"],
            {
                tree_joints["joint/tree_support_fixture/driver_axis"]: 2.0,
                tree_joints["joint/tree_support_fixture/follower_axis"]: 3.0,
            },
        )

    def test_mjcf_exporter_emits_closure_equality_for_kinematic_loop(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            def make_bar(part_id: str, length: float) -> scad.Part:
                body = scad.make_box_rsolid(width=length, height=2.0, depth=2.0)
                body = scad.translate_shape(body, vector=(length / 2.0, 0.0, -1.0))
                part = scad.make_part_rpart(part_id=part_id, body=body)
                part = scad.add_connector_rpart(
                    part,
                    scad.make_placement_connector_rconnector(
                        "pivot_a", scad.identity_placement_rplacement()
                    ),
                )
                return scad.add_connector_rpart(
                    part,
                    scad.make_placement_connector_rconnector(
                        "pivot_b",
                        scad.make_placement_rplacement(origin=(length, 0.0, 0.0)),
                    ),
                )

            @scad.part(id="fb_ground", project_root=Path(__file__).parent)
            def build_ground() -> scad.Part:
                return make_bar("fb_ground", 40.0)

            @scad.part(id="fb_crank", project_root=Path(__file__).parent)
            def build_crank() -> scad.Part:
                return make_bar("fb_crank", 20.0)

            @scad.part(id="fb_coupler", project_root=Path(__file__).parent)
            def build_coupler() -> scad.Part:
                return make_bar("fb_coupler", 50.0)

            @scad.part(id="fb_rocker", project_root=Path(__file__).parent)
            def build_rocker() -> scad.Part:
                return make_bar("fb_rocker", 35.0)

            ground, crank, coupler, rocker = (
                build_ground(),
                build_crank(),
                build_coupler(),
                build_rocker(),
            )

            @scad.assemble(
                id="four_bar_loop",
                definitions=(ground, crank, coupler, rocker),
                project_root=Path(__file__).parent,
            )
            def build_fixture() -> scad.Assembly:
                assembly = scad.make_assembly_rassembly("four_bar_loop")
                assembly = scad.add_component_rassembly(
                    assembly, ground.part, "ground",
                    placement=scad.identity_placement_rplacement(),
                )
                assembly = scad.add_component_rassembly(
                    assembly, crank.part, "crank",
                    placement=scad.identity_placement_rplacement(),
                )
                rocker_direction = (21.875 / 35.0, math.sqrt(746.484375) / 35.0, 0.0)
                rocker_placement = scad.make_placement_rplacement(
                    origin=(40.0, 0.0, 0.0),
                    x_axis=rocker_direction,
                    y_axis=(-rocker_direction[1], rocker_direction[0], 0.0),
                )
                assembly = scad.add_component_rassembly(
                    assembly, rocker.part, "rocker", placement=rocker_placement
                )
                coupler_direction = (41.875 / 50.0, math.sqrt(746.484375) / 50.0, 0.0)
                coupler_placement = scad.make_placement_rplacement(
                    origin=(20.0, 0.0, 0.0),
                    x_axis=coupler_direction,
                    y_axis=(-coupler_direction[1], coupler_direction[0], 0.0),
                )
                assembly = scad.add_component_rassembly(
                    assembly, coupler.part, "coupler", placement=coupler_placement
                )
                assembly = scad.ground_component_rassembly(assembly, "ground")
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly, "crank_to_ground",
                    scad.make_connector_ref_rconnectorref("ground", "pivot_a"),
                    scad.make_connector_ref_rconnectorref("crank", "pivot_a"),
                )
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly, "rocker_to_ground",
                    scad.make_connector_ref_rconnectorref("ground", "pivot_b"),
                    scad.make_connector_ref_rconnectorref("rocker", "pivot_a"),
                )
                assembly = scad.add_revolute_constraint_rassembly(
                    assembly, "coupler_to_crank",
                    scad.make_connector_ref_rconnectorref("crank", "pivot_b"),
                    scad.make_connector_ref_rconnectorref("coupler", "pivot_a"),
                )
                return scad.add_revolute_constraint_rassembly(
                    assembly, "coupler_to_rocker",
                    scad.make_connector_ref_rconnectorref("rocker", "pivot_b"),
                    scad.make_connector_ref_rconnectorref("coupler", "pivot_b"),
                )

            package = scad.build_product_package(build_fixture())
            report = scad.exporter.export_product_package_to_mjcf(
                data=package,
                output_path=root / "loop.xml",
                default_density_kg_m3=1000.0,
            )
            xml_root = ET.parse(report.output_path).getroot()
            mapping = json.loads(report.mapping_path.read_text(encoding="utf-8"))

        connects = xml_root.findall("./equality/connect")
        self.assertEqual(
            [item["joint_id"] for item in mapping["closures"]],
            ["joint/four_bar_loop/coupler_to_rocker"],
        )

    def test_mesh_exporters_reject_invalid_tessellation_parameters(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            package = _build_cylinder_package()

            with self.assertRaisesRegex(ValueError, "linear_deflection"):
                scad.exporter.export_product_package_to_stl(
                    package,
                    root / "invalid.stl",
                    linear_deflection=0.0,
                )
            with self.assertRaisesRegex(ValueError, "angular_deflection_degrees"):
                scad.exporter.export_product_package_to_obj(
                    package,
                    root / "invalid.obj",
                    angular_deflection_degrees=181.0,
                )
            with self.assertRaisesRegex(TypeError, "relative"):
                scad.exporter.export_product_package_to_obj(
                    package,
                    root / "invalid-relative.obj",
                    relative=1,
                )
            with self.assertRaisesRegex(ValueError, "linear_deflection"):
                scad.exporter.export_product_package_to_mjcf(
                    package,
                    root / "invalid.xml",
                    linear_deflection=0.0,
                )
            with self.assertRaisesRegex(ValueError, "angular_deflection_degrees"):
                scad.exporter.export_product_package_to_mjcf(
                    package,
                    root / "invalid-angular.xml",
                    angular_deflection_degrees=181.0,
                )
            self.assertTrue(callable(scad.exporter.tessellate_solid))


if __name__ == "__main__":
    unittest.main()
