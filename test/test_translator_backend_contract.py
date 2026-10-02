"""Contract tests shared by product-package translator backends."""

from __future__ import annotations

import importlib
from pathlib import Path
import unittest

import simplecadapi as scad
from simplecadapi.recording.serializer import CANONICAL_OP_SET
from simplecadapi.topology import OperationGraph
from simplecadapi.translator.freecad_translator.translator import _FreeCADCompiler
from simplecadapi.translator.base import BaseTranslator
from simplecadapi.translator.freecad_translator import FreeCADTranslator
from simplecadapi.translator.freecad_translator.emitters.registry import (
    EMITTER_METHOD_BY_OP,
)
from simplecadapi.translator.freecad_translator.runtime import (
    assemble_runtime_source,
)
from simplecadapi.translator.types import SupportLevel


class TestTranslatorBackendContract(unittest.TestCase):
    def test_backend_packages_have_required_modules(self):
        translator_root = (
            Path(__file__).resolve().parents[1] / "src" / "simplecadapi" / "translator"
        )
        backend_dirs = sorted(
            path
            for path in translator_root.glob("*_translator")
            if (path / "__init__.py").is_file()
        )

        for backend_dir in backend_dirs:
            for filename in (
                "__init__.py",
                "api.py",
                "translator.py",
                "capabilities.py",
            ):
                self.assertTrue(
                    (backend_dir / filename).is_file(),
                    f"{backend_dir.name} is missing required {filename}",
                )

    def test_backend_public_exports_and_capabilities_are_valid(self):
        from simplecadapi import translator

        for backend_package_name in translator.__all__:
            backend = importlib.import_module(
                f"simplecadapi.translator.{backend_package_name}"
            )
            for exported_name in backend.__all__:
                self.assertTrue(hasattr(backend, exported_name))

            capabilities = backend.CAPABILITIES
            expected_backend_name = backend_package_name.removesuffix("_translator")
            self.assertEqual(capabilities.backend_id, expected_backend_name)
            self.assertEqual(set(capabilities.operations), set(CANONICAL_OP_SET))
            self.assertIn(
                "make_set_public_connector_rassembly", capabilities.operations
            )
            self.assertNotIn("make_add_connector_rassembly", capabilities.operations)
            self.assertNotIn(
                "make_forward_connector_rassembly", capabilities.operations
            )

            for op, capability in capabilities.operations.items():
                if capability.level is SupportLevel.UNSUPPORTED:
                    self.assertTrue(capability.reason, op)

            translator_class = getattr(
                backend, f"{capabilities.display_name}Translator"
            )
            self.assertTrue(issubclass(translator_class, BaseTranslator))

    def test_freecad_emitter_registry_matches_declared_support(self):
        from simplecadapi.translator.freecad_translator import CAPABILITIES

        self.assertIs(
            CAPABILITIES.operations["apply_tag_rselection"].level,
            SupportLevel.METADATA_ONLY,
        )
        self.assertIs(
            CAPABILITIES.operations["make_twisted_sweep_rsolid"].level,
            SupportLevel.EMULATED,
        )
        supported_ops = {
            op
            for op, capability in CAPABILITIES.operations.items()
            if capability.level is not SupportLevel.UNSUPPORTED
        }
        self.assertEqual(set(EMITTER_METHOD_BY_OP), supported_ops)

    def test_freecad_runtime_fragments_form_valid_python(self):
        runtime_source = assemble_runtime_source()

        self.assertTrue(runtime_source)
        compile(runtime_source, "<freecad-runtime>", "exec")

    def test_all_translators_are_reusable_for_product_packages(self):
        @scad.part(id="contract_part")
        def build_part() -> scad.Part:
            body = scad.make_box_rsolid(1.0, 2.0, 3.0)
            return scad.make_part_rpart("contract_part", body)

        package = scad.build_product_package(build_part())

        from simplecadapi import translator

        for backend_name in translator.__all__:
            backend = getattr(translator, backend_name)
            translator_class = getattr(
                backend, f"{backend.CAPABILITIES.display_name}Translator"
            )
            instance = translator_class(document_name="ContractTest")
            first = instance.translate_product_package(package)
            second = instance.translate_product_package(package)

            self.assertEqual(first.content, second.content, backend_name)
            self.assertEqual(first.metadata["root_definition_id"], "contract_part")
            self.assertEqual(
                backend.CAPABILITIES.input_schema_versions,
                ("product-package-2.0",),
            )
            compile(first.content, f"<{backend_name}-script>", "exec")

    def test_translator_public_surfaces_do_not_expose_model_json(self):
        from simplecadapi import translator

        for backend_name in translator.__all__:
            backend = getattr(translator, backend_name)
            self.assertFalse(
                any("model_json" in name for name in backend.__all__),
                backend_name,
            )
            self.assertFalse(
                any("ScriptTranslator" in name for name in backend.__all__),
                backend_name,
            )

    def test_new_surface_operations_use_product_translator_compiler(self):
        graph = OperationGraph(graph_id="new_surface_ops")
        carrier = graph.add_node(
            op="make_cylindrical_surface_rface",
            params={
                "radius": 2.0,
                "u_range": (0.0, 1.0),
                "v_range": (0.0, 3.0),
                "origin": (0.0, 0.0, 0.0),
                "axis": (0.0, 0.0, 1.0),
                "x_direction": (1.0, 0.0, 0.0),
                "tolerance": 1.0e-7,
            },
            node_id="carrier",
        )
        boundary = graph.add_node(
            op="make_circle_redge",
            params={
                "radius": 2.0,
                "center": (0.0, 0.0, 0.0),
                "normal": (0.0, 0.0, 1.0),
            },
            node_id="boundary",
        )
        wire = graph.add_node(
            op="make_wire_from_edges_rwire",
            params={"edge_count": 1},
            inputs=[boundary],
            node_id="wire",
        )
        trimmed = graph.add_node(
            op="trim_surface_rface",
            params={"hole_count": 0, "tolerance": 1.0e-7},
            inputs=[carrier, wire],
            node_id="trimmed",
        )
        shell = graph.add_node(
            op="sew_faces_rshell",
            params={"face_count": 1, "tolerance": 1.0e-6},
            inputs=[trimmed],
            node_id="shell",
        )
        solid = graph.add_node(
            op="make_solid_from_shell_rsolid",
            params={},
            inputs=[shell],
            node_id="solid",
        )

        script = _FreeCADCompiler().translate_model_payload_to_script(
            {"graph": graph, "leaf_ids": [solid.node_id]}, graph=graph
        )

        self.assertIn("_cylindrical_surface_shape", script)
        self.assertIn("_trim_surface_shape", script)
        self.assertIn("_solid_from_shell_shape", script)
        compile(script, "<freecad-new-surface-ops>", "exec")

    def test_sidecar_operations_remain_unsupported_by_product_translators(self):
        from simplecadapi import translator

        for backend_name in translator.__all__:
            backend = getattr(translator, backend_name)
            for operation in (
                "load_brep_region_rshell",
                "load_brep_region_rsolid",
            ):
                with self.subTest(backend=backend_name, operation=operation):
                    self.assertIs(
                        backend.CAPABILITIES.operations[operation].level,
                        SupportLevel.UNSUPPORTED,
                    )


if __name__ == "__main__":
    unittest.main()
