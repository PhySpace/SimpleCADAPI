"""Host-independent tests for the SolidWorks product translator."""

from __future__ import annotations

import ast
import importlib
import sys

from test_product_exporter import _build_nested_package


def _model_payload(script: str) -> dict:
    module = ast.parse(script)
    return next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MODEL_PAYLOAD"
            for target in node.targets
        )
    )


def test_backend_imports_without_target_runtime_modules() -> None:
    before = set(sys.modules)

    solidworks = importlib.import_module(
        "simplecadapi.translator.solidworks_translator"
    )

    assert "pythoncom" not in set(sys.modules) - before
    assert "win32com.client" not in set(sys.modules) - before
    assert solidworks.CAPABILITIES.backend_id == "solidworks"
    assert solidworks.CAPABILITIES.input_schema_versions == ("product-package-2.0",)


def test_nested_package_emits_deterministic_compilable_script() -> None:
    from simplecadapi.translator.solidworks_translator import SolidWorksTranslator

    package = _build_nested_package()
    translator = SolidWorksTranslator(document_name="ContractSolidWorks")
    first = translator.translate_product_package(package)
    second = translator.translate_product_package(package)

    assert first.content == second.content
    compile(first.content, "<solidworks-script>", "exec")
    assert first.metadata["root_definition_id"] == "root"
    assert first.metadata["root_definition_kind"] == "assembly"
    assert first.metadata["definition_ids"] == ("linked", "child", "root")
    assert first.metadata["target_runtime_validated"] is False
    assert translator.capabilities.targets[0].requires_external_runtime


def test_product_payload_resolves_references_and_keeps_solved_placements() -> None:
    from simplecadapi.translator.solidworks_translator import SolidWorksTranslator

    script = SolidWorksTranslator().translate_product_package(
        _build_nested_package()
    ).content
    payload = _model_payload(script)
    operations = [node["op"] for node in payload["graph"]["nodes"]]
    evaluations = [
        node["params"]
        for node in payload["graph"]["nodes"]
        if node["op"] == "evaluate_assembly_definition"
    ]

    assert "reference_definition" not in operations
    assert operations.count("make_box_rsolid") == 1
    assert operations.count("evaluate_assembly_definition") == 2
    assert evaluations[0]["constraint_report"]["solved"] is True


def test_script_owns_com_and_contains_native_product_paths() -> None:
    from simplecadapi.translator.solidworks_translator import SolidWorksTranslator

    script = SolidWorksTranslator(visible=True).translate_product_package(
        _build_nested_package()
    ).content

    main_offset = script.index("def main():")
    coinit_offset = script.index("pythoncom.CoInitialize()", main_offset)
    runtime_offset = script.index(
        "runtime = SimpleCADSolidWorksRuntime", main_offset
    )
    assert coinit_offset < runtime_offset
    assert script.count("pythoncom.CoInitialize()") == 1
    assert "runtime.finish()" in script
    assert "self._stop_solidworks()" in script
    assert "if op == 'make_box_rsolid':" in script
    assert "self._extrude_profile(" in script
    assert "if op == 'evaluate_assembly_definition':" in script
    assert "_save_native_assembly" in script
    assert "SimpleCADComponentMap" in script


def test_public_surface_has_no_model_json_or_compiler_entrypoints() -> None:
    from simplecadapi.translator import solidworks_translator as solidworks

    assert "translate_product_package_to_solidworks_script" in solidworks.__all__
    assert all("model_json" not in name for name in solidworks.__all__)
    assert all("ScriptTranslator" not in name for name in solidworks.__all__)
