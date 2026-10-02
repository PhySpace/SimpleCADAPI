"""Host-independent tests for the Fusion 360 product translator."""

from __future__ import annotations

import ast
import importlib
import sys

import pytest

from simplecadapi.product.placement import placement_frame_mm

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

    fusion = importlib.import_module("simplecadapi.translator.fusion360_translator")

    assert "adsk.core" not in set(sys.modules) - before
    assert "adsk.fusion" not in set(sys.modules) - before
    assert fusion.CAPABILITIES.backend_id == "fusion360"
    assert fusion.CAPABILITIES.input_schema_versions == ("product-package-2.0",)


def test_nested_package_emits_deterministic_compilable_script() -> None:
    from simplecadapi.translator.fusion360_translator import Fusion360Translator

    package = _build_nested_package()
    translator = Fusion360Translator(document_name="ContractFusion")
    first = translator.translate_product_package(package)
    second = translator.translate_product_package(package)

    assert first.content == second.content
    compile(first.content, "<fusion360-script>", "exec")
    assert first.metadata["root_definition_id"] == "root"
    assert first.metadata["root_definition_kind"] == "assembly"
    assert first.metadata["definition_ids"] == ("linked", "child", "root")
    assert first.metadata["target_runtime_validated"] is False
    assert translator.capabilities.targets[0].requires_external_runtime


def test_product_payload_resolves_references_and_keeps_solved_placements() -> None:
    from simplecadapi.translator.fusion360_translator import Fusion360Translator

    script = Fusion360Translator().translate_product_package(
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
    inner_b = next(
        record
        for record in evaluations[0]["component_placements"]
        if record["instance_id"] == "inner_b"
    )
    assert placement_frame_mm(inner_b["placement"])["origin"] == pytest.approx(
        [0.0, -0.3882285676537811, 0.051111260566397476]
    )


def test_runtime_uses_shared_nested_product_definitions() -> None:
    from simplecadapi.translator.fusion360_translator import Fusion360Translator

    script = Fusion360Translator().translate_product_package(
        _build_nested_package()
    ).content

    assert "self.product_definition_components = {}" in script
    assert "component.occurrences.addExistingComponent" in script
    assert "self.root.occurrences.addExistingComponent" not in script
    assert "DefinitionKind" in script
    assert "AssemblyEvaluation" in script
    assert "if op == 'make_box_rsolid':" in script
    assert "if op == 'apply_tag_rselection':" in script


def test_public_surface_has_no_model_json_or_compiler_entrypoints() -> None:
    from simplecadapi.translator import fusion360_translator as fusion

    assert "translate_product_package_to_fusion360_script" in fusion.__all__
    assert all("model_json" not in name for name in fusion.__all__)
    assert all("ScriptTranslator" not in name for name in fusion.__all__)
