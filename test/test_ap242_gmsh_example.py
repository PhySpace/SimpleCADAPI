"""Contract tests for the optional AP242-to-Gmsh volume mesh example."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import json
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "ap242_gmsh_volume_mesh"
NOTEBOOK_EXAMPLE = EXAMPLE_DIR / "bracket.py"
PACKAGE_EXAMPLE = EXAMPLE_DIR / "bracket_package.py"
DOWNSTREAM_EXAMPLES = {
    "fcstd": EXAMPLE_DIR / "export_fcstd.py",
    "step": EXAMPLE_DIR / "export_step.py",
    "stl": EXAMPLE_DIR / "export_stl.py",
    "obj": EXAMPLE_DIR / "export_obj.py",
    "freecad_script": EXAMPLE_DIR / "translate_freecad_script.py",
    "fusion360_script": EXAMPLE_DIR / "translate_fusion360_script.py",
    "solidworks_script": EXAMPLE_DIR / "translate_solidworks_script.py",
}
MESH_EXAMPLE = EXAMPLE_DIR / "export_fem_mesh.py"
CALCULIX_EXAMPLE = EXAMPLE_DIR / "run_calculix.py"
VISUALIZATION_EXAMPLE = EXAMPLE_DIR / "visualize_calculix.py"
CONVERGENCE_EXAMPLE = EXAMPLE_DIR / "study_mesh_convergence.py"


def _load_example(path: Path, module_name: str):
    import sys

    # The export scripts import bracket_package from their own directory.
    if str(EXAMPLE_DIR) not in sys.path:
        sys.path.insert(0, str(EXAMPLE_DIR))
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Option:
    def __init__(self):
        self.strings = []
        self.numbers = []

    def setString(self, name, value):
        self.strings.append((name, value))

    def setNumber(self, name, value):
        self.numbers.append((name, value))


class _Occ:
    def __init__(self):
        self.imported = []
        self.synchronized = False

    def importShapes(self, path):
        self.imported.append(path)
        return [(3, 9)]

    def synchronize(self):
        self.synchronized = True


class _Mesh:
    def __init__(self, *, fail=False):
        self.generated = []
        self.fail = fail

    def generate(self, dimension):
        self.generated.append(dimension)
        if self.fail:
            raise RuntimeError("mesh failure")

    def getNodes(self):
        return [1, 2, 3, 4], [0.0] * 12, []

    def getElements(self, dimension):
        return [4], [[20, 21]], [[1, 2, 3, 4, 1, 2, 3, 4]]


class _Model:
    def __init__(self, *, fail=False):
        self.occ = _Occ()
        self.mesh = _Mesh(fail=fail)
        self.models = []
        self.physical_groups = []
        self.physical_names = []

    def add(self, name):
        self.models.append(name)

    def getEntities(self, dimension):
        return [(3, 9)] if dimension == 3 else []

    def addPhysicalGroup(self, dimension, tags):
        self.physical_groups.append((dimension, tags))
        return 7

    def setPhysicalName(self, dimension, tag, name):
        self.physical_names.append((dimension, tag, name))


class _Gmsh:
    def __init__(self, *, fail=False):
        self.option = _Option()
        self.model = _Model(fail=fail)
        self.initialized = 0
        self.finalized = 0
        self.written = []

    def initialize(self):
        self.initialized += 1

    def finalize(self):
        self.finalized += 1

    def write(self, path):
        self.written.append(path)
        Path(path).write_text(
            "$MeshFormat\n4.1 0 8\n$EndMeshFormat\n", encoding="ascii"
        )


class _CalculiXMesh:
    def getNodes(self):
        return (
            [10, 20, 30, 40, 50],
            [
                0.0, 0.0, 0.0,
                1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                0.0, 0.0, 1.0,
                1.0, 1.0, 0.0,
            ],
            [],
        )

    def getElementType(self, family, order):
        self.last_element_request = (family, order)
        return {"Tetrahedron": 4, "Triangle": 2}[family]

    def getElementTypes(self, dimension):
        return [4] if dimension == 3 else []

    def getElementsByType(self, element_type, tag=-1):
        if element_type == 4:
            return [100, 101], [10, 20, 30, 40, 20, 30, 40, 50]
        if element_type == 2 and tag == 22:
            return [200], [20, 30, 50]
        return [], []

    def getNodesForPhysicalGroup(self, dimension, tag):
        self.last_node_group = (dimension, tag)
        return [10, 30, 40], [0.0] * 9


class _CalculiXModel:
    def __init__(self):
        self.mesh = _CalculiXMesh()

    def getPhysicalGroups(self, dimension):
        return [(2, 2), (2, 4)] if dimension == 2 else []

    def getPhysicalName(self, dimension, tag):
        return {
            (2, 2): "interface.fixed_support",
            (2, 4): "interface.load_surface",
        }[(dimension, tag)]

    def getEntitiesForPhysicalGroup(self, dimension, tag):
        return [22] if (dimension, tag) == (2, 4) else []


class _CalculiXGmsh:
    def __init__(self):
        self.model = _CalculiXModel()
        self.initialized = 0
        self.finalized = 0
        self.opened = []

    def initialize(self):
        self.initialized += 1

    def open(self, path):
        self.opened.append(path)

    def finalize(self):
        self.finalized += 1


class TestAP242GmshExample(unittest.TestCase):
    def test_split_example_modules_have_one_responsibility(self):
        from simplecadapi.runtime.config import read_notebook_config

        config = read_notebook_config(NOTEBOOK_EXAMPLE)
        package = _load_example(PACKAGE_EXAMPLE, "ap242_package_example")
        downstream = {
            name: _load_example(path, f"ap242_{name}_example")
            for name, path in DOWNSTREAM_EXAMPLES.items()
        }
        mesh = _load_example(MESH_EXAMPLE, "ap242_mesh_example")
        calculix = _load_example(CALCULIX_EXAMPLE, "ap242_calculix_example")
        visualization = _load_example(
            VISUALIZATION_EXAMPLE,
            "ap242_calculix_visualization_example",
        )

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.id, "ap242_gmsh_bracket")
        self.assertTrue(callable(package.capture_bracket))
        self.assertFalse(hasattr(package, "mesh_step_with_gmsh"))
        self.assertTrue(all(callable(module.main) for module in downstream.values()))
        self.assertTrue(callable(mesh.mesh_step_with_gmsh))
        self.assertTrue(callable(calculix.build_calculix_input))
        self.assertTrue(callable(calculix.run_calculix_static))
        self.assertTrue(callable(visualization.visualize_calculix_result))
        self.assertFalse(hasattr(mesh, "capture_bracket"))
        self.assertEqual(
            {
                package.OUT_DIR,
                mesh.OUT_DIR,
                *(module.OUT_DIR for module in downstream.values()),
            },
            {EXAMPLE_DIR / "out"},
        )

    def test_example_covers_every_package_exporter_and_translator(self):
        import simplecadapi as scad

        self.assertEqual(
            set(DOWNSTREAM_EXAMPLES),
            {
                "fcstd",
                "step",
                "stl",
                "obj",
                "freecad_script",
                "fusion360_script",
                "solidworks_script",
            },
        )
        self.assertTrue(hasattr(scad.exporter, "export_product_package_to_step"))
        self.assertTrue(hasattr(scad.exporter, "export_product_package_to_stl"))
        self.assertTrue(hasattr(scad.exporter, "export_product_package_to_obj"))
        self.assertTrue(
            hasattr(
                scad.translator.freecad_translator,
                "translate_product_package_to_fcstd",
            )
        )
        self.assertTrue(
            hasattr(
                scad.translator.freecad_translator,
                "translate_product_package_to_freecad_script",
            )
        )
        self.assertTrue(
            hasattr(
                scad.translator.fusion360_translator,
                "translate_product_package_to_fusion360_script",
            )
        )
        self.assertTrue(
            hasattr(
                scad.translator.solidworks_translator,
                "translate_product_package_to_solidworks_script",
            )
        )

    def test_mesh_step_uses_occ_volume_mesh_and_reports_counts(self):
        module = _load_example(MESH_EXAMPLE, "ap242_mesh_success_example")
        gmsh = _Gmsh()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            step = root / "part.step"
            step.write_text("STEP", encoding="ascii")
            mesh = root / "part.msh"
            report = module.mesh_step_with_gmsh(
                step,
                mesh,
                mesh_size=1.25,
                gmsh_module=gmsh,
            )

        self.assertEqual(gmsh.initialized, 1)
        self.assertEqual(gmsh.finalized, 1)
        self.assertEqual(gmsh.option.strings, [("Geometry.OCCTargetUnit", "MM")])
        self.assertEqual(
            gmsh.option.numbers,
            [("Mesh.MeshSizeMin", 1.25), ("Mesh.MeshSizeMax", 1.25)],
        )
        self.assertEqual(gmsh.model.mesh.generated, [3])
        self.assertEqual(gmsh.model.physical_groups, [(3, [9])])
        self.assertEqual(report.volume_count, 1)
        self.assertEqual(report.node_count, 4)
        self.assertEqual(report.element_count, 2)

    def test_gmsh_is_finalized_when_meshing_fails(self):
        module = _load_example(MESH_EXAMPLE, "ap242_mesh_failure_example")
        gmsh = _Gmsh(fail=True)
        with tempfile.TemporaryDirectory() as tmp_dir:
            step = Path(tmp_dir) / "part.step"
            step.write_text("STEP", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "mesh failure"):
                module.mesh_step_with_gmsh(
                    step,
                    Path(tmp_dir) / "part.msh",
                    gmsh_module=gmsh,
                )

        self.assertEqual(gmsh.initialized, 1)
        self.assertEqual(gmsh.finalized, 1)

    def test_calculix_input_preserves_node_ids_groups_and_total_load(self):
        module = _load_example(CALCULIX_EXAMPLE, "ap242_calculix_input_example")
        gmsh = _CalculiXGmsh()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            mesh = root / "bracket.msh"
            mesh.write_text("MSH", encoding="ascii")
            input_path = root / "bracket.inp"
            report = module.build_calculix_input(
                mesh,
                input_path,
                load_z_n=-900.0,
                gmsh_module=gmsh,
            )
            deck = input_path.read_text(encoding="ascii")

        self.assertEqual(gmsh.initialized, 1)
        self.assertEqual(gmsh.finalized, 1)
        self.assertEqual(report.node_count, 5)
        self.assertEqual(report.element_count, 2)
        self.assertEqual(report.fixed_node_count, 3)
        self.assertEqual(report.load_node_count, 3)
        self.assertAlmostEqual(report.load_surface_area_mm2, 0.5)
        self.assertAlmostEqual(report.applied_load_z_n, -900.0)
        self.assertIn("10,0,0,0", deck)
        self.assertIn("100,10,20,30,40", deck)
        self.assertIn("FIXED_SUPPORT,1,3", deck)
        self.assertIn("20,3,-300", deck)
        self.assertIn("30,3,-300", deck)
        self.assertIn("50,3,-300", deck)
        self.assertIn("*NODE FILE\nU", deck)
        self.assertIn("*NODE PRINT,NSET=FIXED_SUPPORT,TOTALS=ONLY\nRF", deck)
        self.assertIn("*STATIC,SOLVER=SPOOLES", deck)
        self.assertIn("*EL FILE\nS", deck)

    def test_calculix_input_accepts_iterative_cholesky_solver(self):
        module = _load_example(CALCULIX_EXAMPLE, "ap242_calculix_solver_example")
        gmsh = _CalculiXGmsh()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            mesh = root / "bracket.msh"
            mesh.write_text("MSH", encoding="ascii")
            input_path = root / "bracket.inp"
            report = module.build_calculix_input(
                mesh,
                input_path,
                linear_solver="iterative cholesky",
                gmsh_module=gmsh,
            )
            deck = input_path.read_text(encoding="ascii")

        self.assertEqual(report.linear_solver, "ITERATIVE CHOLESKY")
        self.assertIn("*STATIC,SOLVER=ITERATIVE CHOLESKY", deck)

    def test_calculix_dat_parser_reports_displacement_and_von_mises(self):
        module = _load_example(CALCULIX_EXAMPLE, "ap242_calculix_parser_example")
        with tempfile.TemporaryDirectory() as tmp_dir:
            dat_path = Path(tmp_dir) / "result.dat"
            dat_path.write_text(
                " displacements (vx,vy,vz) for set NALL and time  1.0000000E+00\n"
                " 10  3.0E-01  4.0E-01  0.0E+00\n"
                " 20  0.0E+00  0.0E+00 -2.0E-01\n\n"
                " total force (fx,fy,fz) for set FIXED_SUPPORT and time  1.0000000E+00\n"
                " 0.0E+00 0.0E+00 9.0E+02\n\n"
                " stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) "
                "for set EALL and time  1.0000000E+00\n"
                " 100 1  1.0E+02  0.0E+00  0.0E+00  0.0E+00  0.0E+00  0.0E+00\n"
                " 101 1  0.0E+00  0.0E+00  0.0E+00  5.0E+01  0.0E+00  0.0E+00\n",
                encoding="ascii",
            )
            result = module.parse_calculix_dat(dat_path)

        self.assertAlmostEqual(result["max_displacement_mm"], 0.5)
        self.assertEqual(result["max_displacement_node"], 10)
        self.assertAlmostEqual(result["max_von_mises_mpa"], 100.0)
        self.assertEqual(result["max_von_mises_element"], 100)
        self.assertAlmostEqual(result["reaction_force_z_n"], 900.0)

    def test_calculix_runner_executes_job_and_writes_summary(self):
        module = _load_example(CALCULIX_EXAMPLE, "ap242_calculix_runner_example")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_path = root / "job.inp"
            input_path.write_text("*HEADING\n", encoding="ascii")
            executable = root / "ccx_2.23"
            executable.write_text("#!/bin/sh\n", encoding="ascii")
            executable.chmod(0o755)
            report = module.CalculiXInputReport(
                mesh_path=root / "mesh.msh",
                input_path=input_path,
                node_count=5,
                element_count=2,
                fixed_node_count=3,
                load_node_count=3,
                load_surface_area_mm2=0.5,
                applied_load_z_n=-900.0,
                linear_solver="ITERATIVE CHOLESKY",
            )

            def runner(command, **kwargs):
                self.assertEqual(command, [str(executable.resolve()), "job"])
                self.assertEqual(kwargs["cwd"], root.resolve())
                (root / "job.dat").write_text(
                    " displacements (vx,vy,vz) for set NALL and time 1\n"
                    " 10 0.0 0.0 -0.2\n"
                    " total force (fx,fy,fz) for set FIXED_SUPPORT and time 1\n"
                    " 0 0 900\n"
                    " stresses (elem, integ.pnt.,sxx,syy,szz,sxy,sxz,syz) "
                    "for set EALL and time 1\n"
                    " 100 1 100 0 0 0 0 0\n",
                    encoding="ascii",
                )
                (root / "job.frd").write_text("FRD\n", encoding="ascii")
                return type("Completed", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

            result = module.run_calculix_static(
                report,
                ccx=executable,
                runner=runner,
            )
            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))

        self.assertAlmostEqual(result.max_displacement_mm, 0.2)
        self.assertAlmostEqual(result.max_von_mises_mpa, 100.0)
        self.assertEqual(summary["units"], {"force": "N", "length": "mm", "stress": "MPa"})
        self.assertEqual(summary["input"]["applied_load_z_n"], -900.0)
        self.assertAlmostEqual(result.reaction_force_z_n, 900.0)
        self.assertAlmostEqual(result.force_balance_z_n, 0.0)
        self.assertAlmostEqual(summary["results"]["force_balance_z_n"], 0.0)
        self.assertEqual(summary["input"]["applied_load_z_n"], -900.0)
        self.assertEqual(summary["input"]["linear_solver"], "ITERATIVE CHOLESKY")

    def test_mesh_convergence_requires_a_sustained_platform(self):
        module = _load_example(
            CONVERGENCE_EXAMPLE,
            "ap242_mesh_convergence_assessment_example",
        )

        def level(mesh_size, displacement_change, stress_change):
            return module.MeshConvergenceLevel(
                mesh_size_mm=mesh_size,
                node_count=1,
                element_count=1,
                fixed_node_count=1,
                load_node_count=1,
                max_displacement_mm=1.0,
                max_von_mises_mpa=1.0,
                reaction_force_z_n=1.0,
                force_balance_z_n=0.0,
                displacement_change_from_previous=displacement_change,
                stress_change_from_previous=stress_change,
                mesh_path="mesh.msh",
                input_path="job.inp",
                summary_path="job.json",
            )

        transient = module.assess_mesh_convergence(
            [
                level(3.0, None, None),
                level(2.0, 0.04, 0.09),
                level(1.5, 0.08, 0.05),
            ]
        )
        sustained = module.assess_mesh_convergence(
            [
                level(3.0, None, None),
                level(2.0, 0.20, 0.20),
                level(1.5, 0.04, 0.09),
                level(1.0, 0.03, 0.08),
            ],
            required_platform_pairs=2,
        )

        self.assertFalse(transient["platform_reached"])
        self.assertIsNone(transient["recommended_mesh_size_mm"])
        self.assertTrue(sustained["platform_reached"])
        self.assertEqual(sustained["production_level_n_minus_1"], 3)
        self.assertEqual(sustained["verification_level_n"], 4)
        self.assertEqual(sustained["recommended_mesh_size_mm"], 1.5)

    def test_mesh_convergence_reports_only_sustained_platform_as_independent(self):
        module = _load_example(
            CONVERGENCE_EXAMPLE,
            "ap242_mesh_convergence_independence_example",
        )

        def level(mesh_size, displacement_change, stress_change):
            return module.MeshConvergenceLevel(
                mesh_size_mm=mesh_size,
                node_count=1,
                element_count=1,
                fixed_node_count=1,
                load_node_count=1,
                max_displacement_mm=1.0,
                max_von_mises_mpa=1.0,
                reaction_force_z_n=1.0,
                force_balance_z_n=0.0,
                displacement_change_from_previous=displacement_change,
                stress_change_from_previous=stress_change,
                mesh_path="mesh.msh",
                input_path="job.inp",
                summary_path="job.json",
            )

        assessment = module.assess_mesh_convergence(
            [
                level(0.75, None, None),
                level(0.5, 0.03, 0.19),
                level(0.375, 0.01, 0.03),
            ]
        )

        self.assertFalse(assessment["mesh_independent"])
        self.assertTrue(assessment["finest_pair_displacement_within_tolerance"])
        self.assertTrue(assessment["finest_pair_stress_within_tolerance"])
        self.assertIsNone(assessment["recommended_mesh_size_mm"])

    def test_calculix_visualizer_converts_frd_to_nonempty_vtu(self):
        module = _load_example(
            VISUALIZATION_EXAMPLE,
            "ap242_calculix_vtu_example",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            frd = root / "job.frd"
            frd.write_text("FRD\n", encoding="ascii")

            class Converter:
                def __init__(self, source, formats):
                    self.source = Path(source)
                    self.formats = formats

                def run(self):
                    self.assert_formats = self.formats
                    self.source.with_suffix(".vtu").write_text("VTU\n", encoding="ascii")

            vtu = module.convert_frd_to_vtu(frd, converter_class=Converter)

        self.assertEqual(vtu.name, "job.vtu")


if __name__ == "__main__":
    unittest.main()
