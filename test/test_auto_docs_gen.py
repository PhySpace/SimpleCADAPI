import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools/auto_docs_gen.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "simplecadapi_auto_docs_gen",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")

auto_docs_gen = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = auto_docs_gen
MODULE_SPEC.loader.exec_module(auto_docs_gen)


class TestAutoDocsGenPathResolution(unittest.TestCase):
    def test_resolve_source_files_from_repo_checkout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            (project_root / "pyproject.toml").write_text(
                "[project]\nname = 'demo'\n",
                encoding="utf-8",
            )

            module_file = project_root / "tools/auto_docs_gen.py"
            module_file.parent.mkdir(parents=True, exist_ok=True)
            module_file.write_text("", encoding="utf-8")

            resolved = auto_docs_gen._resolve_source_files(
                None, module_file=module_file
            )
            package_root = project_root / "src/simplecadapi"
            expected = [
                (package_root / name).resolve()
                for name in auto_docs_gen.DEFAULT_SOURCE_FILENAMES
            ]

            self.assertEqual(resolved, expected)

    def test_resolve_source_files_outside_repo_fails_loud(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            module_file = Path(tmp_dir) / "auto_docs_gen.py"
            module_file.write_text("", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                auto_docs_gen._resolve_source_files(None, module_file=module_file)

    def test_resolve_output_dirs_from_source_checkout_uses_repo_docs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            (project_root / "pyproject.toml").write_text(
                "[project]\nname = 'demo'\n",
                encoding="utf-8",
            )

            module_file = project_root / "tools/auto_docs_gen.py"
            module_file.parent.mkdir(parents=True, exist_ok=True)
            module_file.write_text("", encoding="utf-8")

            resolved = auto_docs_gen._resolve_output_dirs(None, module_file=module_file)

            self.assertEqual(
                resolved,
                [(project_root / "docs/skill/references/docs/api").resolve()],
            )

    def test_default_source_files_include_v2_public_modules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_root = Path(tmp_dir) / "src/simplecadapi"
            package_root.mkdir(parents=True, exist_ok=True)
            backend_root = package_root / "translator/freecad_translator"
            backend_root.mkdir(parents=True)
            (backend_root / "api.py").write_text("", encoding="utf-8")
            (backend_root / "translator.py").write_text("", encoding="utf-8")
            (backend_root / "types.py").write_text("", encoding="utf-8")

            resolved = auto_docs_gen._default_source_files(package_root)

            resolved_names = [
                path.relative_to(package_root).as_posix() for path in resolved
            ]
            self.assertIn("recording/serializer.py", resolved_names)
            self.assertIn("recording/graph.py", resolved_names)
            self.assertIn("params/expr.py", resolved_names)
            self.assertIn("params/tolerance.py", resolved_names)
            self.assertIn("sketch.py", resolved_names)
            self.assertIn("math.py", resolved_names)
            self.assertIn("translator/freecad_translator/api.py", resolved_names)
            self.assertIn(
                "translator/freecad_translator/translator.py",
                resolved_names,
            )
            self.assertIn(
                "translator/freecad_translator/types.py",
                resolved_names,
            )
            self.assertIn("inspect/brep/inspect.py", resolved_names)
            self.assertIn("inspect/brep/manufacturing.py", resolved_names)
            self.assertIn("inspect/brep/queries.py", resolved_names)
            self.assertIn("exporter/mjcf.py", resolved_names)

    def test_default_source_files_include_build_public_surface(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_root = Path(tmp_dir) / "src/simplecadapi"
            package_root.mkdir(parents=True, exist_ok=True)
            resolved = auto_docs_gen._default_source_files(package_root)
            resolved_names = [
                path.relative_to(package_root).as_posix() for path in resolved
            ]

            self.assertIn("build/part_builder.py", resolved_names)
            self.assertIn("build/assembly_builder.py", resolved_names)
            self.assertIn("build/dependencies.py", resolved_names)
            self.assertIn("build/results.py", resolved_names)
            self.assertIn("product/capture.py", resolved_names)
            self.assertNotIn("cache/policy.py", resolved_names)

    def test_real_build_sources_document_only_top_level_surface(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=auto_docs_gen._default_source_files(
                    Path(__file__).resolve().parents[1] / "src/simplecadapi"
                ),
                output_dirs=[Path(tmp_dir) / "docs/api"],
                quiet=True,
            )
            names = {api.name for api in generator.extract_apis()}
            for name in (
                "capture",
                "CaptureResult",
                "assemble",
                "file_input",
                "part",
                "AssemblyBuildResult",
                "PartBuildResult",
                "ProductMJCFExportReport",
                "export_product_package_to_mjcf",
            ):
                self.assertIn(name, names)
            self.assertNotIn("snapshot_file_inputs", names)
            self.assertNotIn("OperationCacheReport", names)
            self.assertNotIn("operation_cache_scope", names)
            self.assertNotIn("operation_cache_report", names)

    def test_inspect_brep_api_docs_use_inspection_namespace(self):
        class InspectionDocGenerator(auto_docs_gen.APIDocumentGenerator):
            def _module_name_for(self, file_path):
                return "inspect/brep/inspect.py"

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            package_root = tmp_path / "simplecadapi"
            source_file = package_root / "inspect/brep/inspect.py"
            source_file.parent.mkdir(parents=True)
            (package_root / "__init__.py").write_text(
                "__all__ = ['inspect']\n",
                encoding="utf-8",
            )
            source_file.write_text(
                "def inspect_step_rsummary(path: str) -> dict:\n"
                '    """Inspect one STEP summary."""\n'
                "    return {}\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"
            generator = InspectionDocGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            page = (output_dir / "inspect_step_rsummary.md").read_text(encoding="utf-8")
            self.assertIn("## STEP/BREP Inspection", readme)
            self.assertIn("`inspection namespace`", readme)
            self.assertIn("from simplecadapi.inspect import brep", page)
            self.assertIn("unavailable inside GraphSession", page)

    def test_real_drawing_sources_export_namespace_and_acceptance_docs(self):
        project_root = MODULE_PATH.parents[1]
        source_root = project_root / "src/simplecadapi"
        sources = [
            path
            for path in auto_docs_gen._default_source_files(source_root)
            if path.parent == source_root / "inspect/drawing"
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir)
            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=sources, output_dirs=[output], quiet=True
            )
            apis = generator.extract_apis()
            generator.generate_markdown_docs()
            names = {api.name for api in apis}
            self.assertTrue(
                {
                    "DrawingSectionDimensions",
                    "DrawingText",
                    "extract_drawing_primitives_rstrokes",
                    "measure_model_section_rdimensions",
                    "validate_section_annotations_rreport",
                    "assess_dimension_rverdict",
                }
                <= names
            )
            self.assertNotIn("section_geometry", names)
            self.assertNotIn("fit_circle_diagnostics", names)
            for api in apis:
                self.assertIn("drawing-inspection namespace", api.import_surface)
                self.assertIn("unavailable inside GraphSession", api.import_surface)
            self.assertIn(
                "## Drawing Inspection",
                (output / "README.md").read_text(encoding="utf-8"),
            )
            measure = (output / "measure_model_section_rdimensions.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("section_checks", measure)
            self.assertIn("unknown", measure.lower())

    def test_evaluator_api_docs_preserve_schemas_units_and_trust_boundaries(self):
        class EvaluationDocGenerator(auto_docs_gen.APIDocumentGenerator):
            def _module_name_for(self, file_path):
                return "inverse_engineer/brep/evaluation.py"

        project_root = MODULE_PATH.parents[1]
        source_file = (
            project_root / "src/simplecadapi/inverse_engineer/brep/evaluation.py"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "docs/api"
            generator = EvaluationDocGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            bundle = (output_dir / "run_comparison_bundle.md").read_text(
                encoding="utf-8"
            )
            config = (output_dir / "EvaluationConfig.md").read_text(encoding="utf-8")
            classify = (output_dir / "classify_benchmark_result.md").read_text(
                encoding="utf-8"
            )
            section = (output_dir / "SectionEvaluationConfig.md").read_text(
                encoding="utf-8"
            )

            self.assertIn("## Reconstruction Evaluation", readme)
            self.assertIn("`reverse-engineering evaluator`", readme)
            self.assertIn("from simplecadapi.inverse_engineer.brep import", bundle)
            self.assertNotIn("top-level:", bundle)
            self.assertIn("Report schemas and units", bundle)
            self.assertIn("cubic millimetres", bundle)
            self.assertIn("checks.hard_gate", bundle)
            self.assertIn(
                "diagnostic, never equality proof",
                " ".join(bundle.split()),
            )
            self.assertIn("diagnostics and never affect classification", bundle)
            self.assertIn("status ``completed``", bundle)
            self.assertIn("``gate_passed=None``", bundle)
            self.assertIn("strict bidirectional", bundle)
            self.assertIn("non-fuzzy bidirectional Cut residual volumes", bundle)
            self.assertIn("mass-property comparison", bundle)
            for deprecated in (
                "global_max_bbox_delta",
                "global_max_centroid_distance",
                "global_max_relative_volume_error",
                "global_max_relative_area_error",
                "boundary_max_hausdorff",
                "boundary_max_p95",
            ):
                self.assertIn(deprecated, config)
            self.assertIn("deprecated compatibility inputs and are ignored", config)
            self.assertIn("strict_material_tolerance", config)
            self.assertIn("boundary_linear_deflection", config)
            self.assertIn("boundary_max_samples", config)
            self.assertIn("strict_geometric_tolerance", config)
            self.assertIn("unmodified, process-local result", classify)
            self.assertIn("ignored by classification", classify)
            self.assertIn("at least one unique face", classify)
            self.assertIn(
                "not just a claimed stage status",
                " ".join(classify.split()),
            )
            self.assertIn("bounded diagnostic section probe", section)
            self.assertIn("not acceptance gates", section)
            self.assertIn("require_nonempty", section)
            self.assertIn("max_hausdorff", section)
            self.assertIn("max_relative_area_error", section)
            self.assertIn("deprecated compatibility inputs", section)
            self.assertIn("do not affect stage status", section)

    def test_persistence_api_docs_distinguish_roundtrip_from_target_similarity(self):
        class PersistenceDocGenerator(auto_docs_gen.APIDocumentGenerator):
            def _module_name_for(self, file_path):
                return "inspect/brep/persistence.py"

        project_root = MODULE_PATH.parents[1]
        source_file = project_root / "src/simplecadapi/inspect/brep/persistence.py"
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "docs/api"
            generator = PersistenceDocGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            persistence = (
                output_dir / "validate_step_roundtrip_rdescriptor.md"
            ).read_text(encoding="utf-8")
            self.assertIn("candidate-before/after volume and surface-area", persistence)
            self.assertIn("STEP serialization integrity checks", persistence)
            self.assertIn("not candidate-to-target", persistence)

    def test_manufacturing_module_generates_public_api_pages(self):
        project_root = Path(__file__).resolve().parents[1]
        source_file = (
            project_root / "src/simplecadapi/inspect/brep/manufacturing.py"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "docs/api"
            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )

            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            self.assertTrue(
                (output_dir / "inspect_manufacturing_hints_rdescriptor.md").exists()
            )
            self.assertTrue(
                (output_dir / "render_manufacturing_hints_rpath.md").exists()
            )
            self.assertIn("inspect_manufacturing_hints_rdescriptor", readme)
            self.assertIn("render_manufacturing_hints_rpath", readme)
            renderer_page = (
                output_dir / "render_manufacturing_hints_rpath.md"
            ).read_text(encoding="utf-8")
            self.assertNotIn("report:", renderer_page)

    def test_default_stdlib_source_files_include_standard_modules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            package_root = Path(tmp_dir) / "src/simplecadapi"
            package_root.mkdir(parents=True, exist_ok=True)

            resolved = auto_docs_gen._default_stdlib_source_files(package_root)

            self.assertEqual(
                resolved,
                [
                    package_root / "std/bearing.py",
                    package_root / "std/gear.py",
                ],
            )

    def test_resolve_stdlib_output_dirs_from_source_checkout_uses_repo_docs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir)
            (project_root / "pyproject.toml").write_text(
                "[project]\nname = 'demo'\n",
                encoding="utf-8",
            )

            module_file = project_root / "tools/auto_docs_gen.py"
            module_file.parent.mkdir(parents=True, exist_ok=True)
            module_file.write_text("", encoding="utf-8")

            resolved = auto_docs_gen._resolve_stdlib_output_dirs(
                None,
                module_file=module_file,
            )

            self.assertEqual(
                resolved,
                [(project_root / "docs/skill/references/docs/stdlib").resolve()],
            )


class TestAutoDocsGenExtraction(unittest.TestCase):
    def test_extract_apis_from_v2_public_modules(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "pkg").mkdir()
            (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (tmp_path / "pkg" / "recording").mkdir()
            (tmp_path / "pkg" / "recording" / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            source_file = tmp_path / "pkg" / "recording" / "serializer.py"
            source_file.write_text(
                """
def export_model_json(session, indent=2):
    \"\"\"Export the canonical 2.0 model seed JSON.\"\"\"
    return \"{}\"


def _internal_helper():
    \"\"\"Should not be documented.\"\"\"
    return None
""".strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )

            apis = generator.extract_apis()

            self.assertEqual([api.name for api in apis], ["export_model_json"])

    def test_generate_markdown_includes_v2_model_api_entry(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "pkg").mkdir()
            (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (tmp_path / "pkg" / "recording").mkdir()
            (tmp_path / "pkg" / "recording" / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            source_file = tmp_path / "pkg" / "recording" / "serializer.py"
            source_file.write_text(
                """
def export_model_json(session, indent=2):
    \"\"\"Export the canonical 2.0 model seed JSON.

    Args:
        session: Recorded graph session.
        indent: JSON indentation level.

    Returns:
        JSON string representation.
    \"\"\"
    return \"{}\"
""".strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            page = (output_dir / "export_model_json.md").read_text(encoding="utf-8")

            self.assertIn("[export_model_json](export_model_json.md)", readme)
            self.assertIn("def export_model_json(session, indent = 2)", page)
            self.assertIn("Export the canonical 2.0 model seed JSON.", page)

    def test_generate_markdown_avoids_case_insensitive_filename_collisions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "pkg").mkdir()
            (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (tmp_path / "pkg" / "params").mkdir()
            (tmp_path / "pkg" / "params" / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            source_file = tmp_path / "pkg" / "params" / "expr.py"
            source_file.write_text(
                """
class Const:
    \"\"\"Constant node.\"\"\"


def const(value):
    \"\"\"Constant constructor.\"\"\"
    return value
""".strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")

            self.assertTrue((output_dir / "Const.md").exists())
            self.assertTrue((output_dir / "const_function.md").exists())
            self.assertIn("[Const](Const.md)", readme)
            self.assertIn("[const](const_function.md)", readme)

    def test_generate_markdown_includes_math_helper_category(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            init_file = tmp_path / "__init__.py"
            init_file.write_text(
                "__all__ = ['BSplineFitResult', 'fit_cubic_bspline_control_points']\n",
                encoding="utf-8",
            )
            source_file = tmp_path / "math.py"
            source_file.write_text(
                '''
class BSplineFitResult:
    """B-spline fitting result."""


def fit_cubic_bspline_control_points(sample_points, *, tolerance=1e-3):
    """Fit sampled points to cubic B-spline controls."""
    return BSplineFitResult()
'''.strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")

            self.assertIn("## Math Helpers", readme)
            self.assertIn("[BSplineFitResult](BSplineFitResult.md)", readme)
            self.assertIn(
                "[fit_cubic_bspline_control_points](fit_cubic_bspline_control_points.md)",
                readme,
            )

    def test_generate_markdown_includes_top_level_exported_operations_class(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "__init__.py").write_text(
                "__all__ = ['SurfaceSettings']\n", encoding="utf-8"
            )
            source_file = tmp_path / "ql.py"
            source_file.write_text(
                '''
from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceSettings:
    """Surface construction settings."""

    degree: int = 3
'''.strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file], output_dirs=[output_dir], quiet=True
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            page = (output_dir / "SurfaceSettings.md").read_text(encoding="utf-8")
            self.assertIn("[SurfaceSettings](SurfaceSettings.md)", readme)
            self.assertIn("class SurfaceSettings(degree: int = 3)", page)
            self.assertIn("from simplecadapi import SurfaceSettings", page)

    def test_generate_markdown_includes_physical_units_category(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            (tmp_path / "pkg" / "params").mkdir(parents=True)
            init_file = tmp_path / "pkg" / "__init__.py"
            init_file.write_text(
                "__all__ = ['Dimension', 'convert_value']\n", encoding="utf-8"
            )
            (tmp_path / "pkg" / "params" / "__init__.py").write_text(
                "", encoding="utf-8"
            )
            source_file = tmp_path / "pkg" / "params" / "units.py"
            source_file.write_text(
                '''
class Dimension:
    """Physical dimension."""


def convert_value(value, from_unit, to_unit):
    """Convert compatible units."""
    return value
'''.strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/api"

            generator = auto_docs_gen.APIDocumentGenerator(
                source_files=[source_file], output_dirs=[output_dir], quiet=True
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")

            self.assertIn("## Physical Units", readme)
            self.assertIn("[Dimension](Dimension.md)", readme)
            self.assertIn("[convert_value](convert_value.md)", readme)

    def test_generate_stdlib_markdown_uses_stdlib_index_and_import_surface(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_dir = tmp_path / "std"
            source_dir.mkdir()
            source_file = source_dir / "gear.py"
            source_file.write_text(
                '''
def make_spur_gear_rsolid(n_teeth: int, module: float):
    """Create a test spur gear.

    Parameters
    ----------
    n_teeth : int
        Number of teeth.
    module : float
        Gear module.
    """
    return None


def _private_helper():
    """Should not be documented."""
    return None
'''.strip()
                + "\n",
                encoding="utf-8",
            )
            output_dir = tmp_path / "docs/stdlib"

            generator = auto_docs_gen.StdlibDocumentGenerator(
                source_files=[source_file],
                output_dirs=[output_dir],
                quiet=True,
            )
            generator.extract_apis()
            generator.generate_markdown_docs()

            readme = (output_dir / "README.md").read_text(encoding="utf-8")
            page = (output_dir / "make_spur_gear_rsolid.md").read_text(encoding="utf-8")

            self.assertIn("# SimpleCAD Standard Library Index", readme)
            self.assertIn("[make_spur_gear_rsolid](make_spur_gear_rsolid.md)", readme)
            self.assertIn("scad.std.gear.make_spur_gear_rsolid", page)
            self.assertIn("**Type**: `int`", page)
            self.assertNotIn("_private_helper", readme)


if __name__ == "__main__":
    unittest.main()
