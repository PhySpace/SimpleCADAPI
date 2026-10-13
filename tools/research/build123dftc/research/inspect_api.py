"""Generate a version-specific public build123d API and corpus inventory.

This is research evidence, not a declaration that conversion is implemented.
Run with the same interpreter as the source model corpus.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from enum import Enum
import inspect
import hashlib
import json
from pathlib import Path
from typing import Any


DOCUMENTATION_SOURCES = [
    "https://build123d.readthedocs.io/en/v0.13.0/objects.html",
    "https://build123d.readthedocs.io/en/v0.13.0/operations.html",
    "https://build123d.readthedocs.io/en/v0.13.0/key_concepts_builder.html",
    "https://build123d.readthedocs.io/en/v0.13.0/key_concepts_algebra.html",
    "https://build123d.readthedocs.io/en/v0.13.0/direct_api_reference.html",
]

OPERATORS = {
    "__add__", "__radd__", "__sub__", "__and__", "__mul__", "__rmul__",
    "__matmul__", "__xor__", "__mod__", "__neg__", "__invert__",
}
TRANSFORMS = {
    "move", "moved", "locate", "located", "translate", "rotate", "scale",
    "mirror", "transform_shape", "transform_geometry", "transformed",
}
FEATURES = {
    "extrude", "extrude_taper", "extrude_until", "extrude_linear_with_rotation",
    "revolve", "sweep", "sweep_multi", "loft", "fillet", "chamfer", "draft",
    "hollow", "offset", "offset_2d", "offset_3d", "split", "split_by_perimeter",
    "thicken", "dprism", "trim", "trim_infinite", "trim_to_length",
    "trim_to_other", "make_holes", "without_holes", "close", "stitch", "combine",
    "clean", "fix", "fix_degenerate_edges", "to_splines", "reversed", "wrap",
    "wrap_faces", "cut", "fuse", "intersect", "fillet_2d", "chamfer_2d",
    "project", "project_to_shape", "project_faces", "sew_faces",
}


def category(name: str, obj: Any) -> str:
    module = getattr(obj, "__module__", "")
    if inspect.isclass(obj) and issubclass(obj, Enum):
        return "enum"
    if module.startswith("build123d.operations_"):
        return "operation"
    if module.startswith("build123d.objects_"):
        return "object_" + module.removeprefix("build123d.objects_")
    if name.startswith("Build"):
        return "builder"
    if name.endswith("Locations") or name == "Locations":
        return "locations"
    if module.startswith("build123d.topology"):
        return "direct_topology"
    if module == "build123d.geometry":
        return "geometry"
    if "export" in module or name.startswith("Export"):
        return "export"
    if "import" in module or name.startswith("import_"):
        return "import"
    if module == "build123d.joints":
        return "assembly_joint"
    if module == "build123d.drafting":
        return "drawing_object"
    if not callable(obj):
        return "constant_or_type_alias"
    return "utility"


def source_info(obj: Any, package_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        source = Path(inspect.getsourcefile(obj) or "")
        result["source_file"] = str(source.relative_to(package_dir.parent))
        result["source_line"] = inspect.getsourcelines(obj)[1]
    except (TypeError, ValueError, OSError):
        pass
    try:
        result["signature"] = str(inspect.signature(obj))
    except (TypeError, ValueError):
        pass
    return result


def member_category(name: str, raw: Any, owner: type) -> str:
    if isinstance(raw, property):
        return "property"
    if name in OPERATORS:
        return "algebra_operator"
    if name in TRANSFORMS:
        return "transform"
    if name.startswith("make_") or name == "from_bounding_box":
        return "factory"
    if name in FEATURES:
        return "feature"
    if name in {"__enter__", "__exit__"}:
        return "context_lifecycle"
    if issubclass(owner, Enum):
        return "enum_member"
    return "query_or_utility"


class ModelVisitor(ast.NodeVisitor):
    """Count modeling calls, excluding entrypoint and constant-false docs branches."""

    def __init__(self, exports: set[str]):
        self.exports = exports
        self.constants: dict[str, Any] = {}
        self.calls: Counter[str] = Counter()
        self.methods: Counter[str] = Counter()
        self.operators: Counter[str] = Counter()
        self.builders = False
        self.aliases = {"build123d"}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "build123d":
                self.aliases.add(alias.asname or alias.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.constants[target.id] = node.value.value
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test = node.test
        is_entrypoint = (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        )
        if is_entrypoint:
            return
        if isinstance(test, ast.Name) and self.constants.get(test.id) is False:
            for stmt in node.orelse:
                self.visit(stmt)
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.exports:
            self.calls[func.id] += 1
            self.builders |= func.id in {"BuildLine", "BuildSketch", "BuildPart"}
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in self.aliases:
                self.calls[func.attr] += 1
                self.builders |= func.attr in {"BuildLine", "BuildSketch", "BuildPart"}
            else:
                self.methods[func.attr] += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        self.operators[type(node.op).__name__] += 1
        self.generic_visit(node)


def inventory(manifest_path: Path) -> dict[str, Any]:
    import build123d as bd
    from build123d.build_common import BaseObjectMeta, Builder
    from build123d.topology.shape_core import Shape
    from build123d.topology.one_d import Mixin1D
    from build123d.topology.two_d import Mixin2D
    from build123d.topology.three_d import Mixin3D

    package_dir = Path(bd.__file__).parent
    manifest = json.loads(manifest_path.read_text())
    top_level: list[dict[str, Any]] = []
    members: dict[str, dict[str, Any]] = {}
    classes: dict[str, list[str]] = {}
    extra_classes = [Shape, Mixin1D, Mixin2D, Mixin3D, Builder, BaseObjectMeta]
    for name in bd.__all__:
        obj = getattr(bd, name)
        record = {
            "name": name,
            "kind": "class" if inspect.isclass(obj) else "function" if callable(obj) else "value",
            "category": category(name, obj),
            "module": getattr(obj, "__module__", type(obj).__module__),
            "conversion_status": "unverified",
            **source_info(obj, package_dir),
        }
        if inspect.isclass(obj) and issubclass(obj, Enum):
            record["values"] = list(obj.__members__)
        top_level.append(record)
        if inspect.isclass(obj):
            extra_classes.append(obj)
    for cls in dict.fromkeys(extra_classes):
        refs = []
        for name in sorted(dir(cls)):
            if name.startswith("_") and name not in OPERATORS | {"__enter__", "__exit__", "__call__"}:
                continue
            owner = next((parent for parent in cls.__mro__ if name in vars(parent)), None)
            if owner is None or not owner.__module__.startswith("build123d"):
                continue
            raw = vars(owner)[name]
            value = raw.fget if isinstance(raw, property) else raw.__func__ if isinstance(raw, (staticmethod, classmethod)) else raw
            if not callable(value) and not isinstance(raw, property):
                continue
            key = owner.__module__ + "." + owner.__name__ + "." + name
            refs.append(key)
            if key not in members:
                members[key] = {
                    "name": name,
                    "owner": owner.__module__ + "." + owner.__name__,
                    "category": member_category(name, raw, owner),
                    "descriptor": "property" if isinstance(raw, property) else "classmethod" if isinstance(raw, classmethod) else "staticmethod" if isinstance(raw, staticmethod) else "method",
                    "conversion_status": "unverified",
                    **source_info(value, package_dir),
                }
        classes[cls.__module__ + "." + cls.__name__] = refs
    models = []
    all_calls: Counter[str] = Counter()
    all_methods: Counter[str] = Counter()
    for item in manifest["examples"]:
        model_path = manifest_path.parent / item["file"]
        visitor = ModelVisitor(set(bd.__all__))
        visitor.visit(ast.parse(model_path.read_text()))
        all_calls.update(visitor.calls)
        all_methods.update(visitor.methods)
        models.append({
            "id": item["id"], "name": item["name"], "file": item["file"],
            "source_url": item["source_url"],
            "builder_context_present": visitor.builders,
            "top_level_call_sites": dict(visitor.calls.most_common()),
            "method_call_sites": dict(visitor.methods.most_common()),
            "operator_syntax_counts": dict(visitor.operators.most_common()),
        })
    return {
        "schema_version": 1,
        "purpose": "Version-specific API inventory and static source corpus evidence; unverified is not implemented support.",
        "build123d_version": bd.__version__,
        "corpus_tag": manifest["tag"],
        "corpus_commit": manifest["commit"],
        "sources": DOCUMENTATION_SOURCES,
        "scope": "203 package __all__ exports plus public build123d-declared members reachable through these classes, Shape, topology mixins and Builder; Python/OCP internals are excluded.",
        "counts": {
            "top_level_exports": len(top_level), "unique_public_member_declarations": len(members),
            "class_interfaces": len(classes), "corpus_models": len(models),
            "corpus_distinct_top_level_calls": len(all_calls),
            "corpus_top_level_call_sites": sum(all_calls.values()),
            "top_level_by_category": dict(Counter(item["category"] for item in top_level)),
            "members_by_category": dict(Counter(item["category"] for item in members.values())),
        },
        "top_level_api": top_level,
        "members": members,
        "class_members": classes,
        "corpus": {
            "counting_note": "AST call sites, not runtime execution counts. Constant-false GEN_DOCS branches and __main__ export blocks are omitted; loops/functions are counted syntactically. Operator counts include numeric arithmetic.",
            "top_level_calls": dict(all_calls.most_common()),
            "method_calls": dict(all_methods.most_common()),
            "models": models,
        },
    }


def validation_evidence(data: dict[str, Any], report_path: Path, traces_dir: Path | None) -> None:
    """Link only verified samples, never promote an entire API parameter space."""
    report = json.loads(report_path.read_text())
    rows = {row["stem"]: row for row in report["rows"]}
    accepted = {stem for stem, row in rows.items() if row.get("quality") == "accepted"}
    usage: dict[str, set[str]] = {}
    for model in data["corpus"]["models"]:
        stem = Path(model["file"]).stem
        for api in model["top_level_call_sites"]:
            usage.setdefault(api, set()).add(stem)
    observed_members: dict[str, set[str]] = {}
    if traces_dir is not None:
        for path in traces_dir.glob("*.trace.json"):
            stem = path.name.removesuffix(".trace.json")
            trace = json.loads(path.read_text())
            for step in trace.get("steps", []):
                source = step.get("source")
                if source and step.get("op") != "unsupported":
                    observed_members.setdefault(source, set()).add(stem)
    source_report = {"path": str(report_path),
                     "sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()}
    for record in data["top_level_api"]:
        exercised = usage.get(record["name"], set())
        verified = sorted(exercised & accepted)
        if verified:
            record["conversion_status"] = "verified_sampled_usage"
        record["validation_evidence"] = {
            "accepted_models": verified,
            "rejected_or_unverified_models": sorted(exercised - accepted),
            "scope": "Model-level evidence for the listed source calls only; other argument variants remain unverified.",
        }
    for record in data["members"].values():
        source = record["owner"].rsplit(".", 1)[-1] + "." + record["name"]
        exercised = observed_members.get(source, set())
        verified = sorted(exercised & accepted)
        if verified:
            record["conversion_status"] = "verified_sampled_usage"
            record["validation_evidence"] = {"accepted_models": verified,
                "scope": "Captured member call in accepted models; other argument variants remain unverified."}
    data["verification"] = {"source_report": source_report,
        "accepted_models": sorted(accepted),
        "rejected_or_unverified_models": sorted(set(rows) - accepted),
        "scope": "Sample-level acceptance is not a claim of all-API or all-parameter coverage.",
        "verified_top_level_entries": sum(r["conversion_status"] == "verified_sampled_usage" for r in data["top_level_api"]),
        "verified_public_member_entries": sum(r["conversion_status"] == "verified_sampled_usage" for r in data["members"].values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-report", type=Path, help="Optional strict stage-3 report for sample evidence")
    parser.add_argument("--traces-dir", type=Path, help="Trace source member names supporting the validation report")
    args = parser.parse_args()
    data = inventory(args.manifest.resolve())
    if args.validation_report is not None:
        validation_evidence(data, args.validation_report, args.traces_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(data["counts"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
