#!/usr/bin/env python3
"""Generate markdown API docs from source files.

The generator extracts top-level public functions from source files,
parses their docstrings, and writes API markdown pages plus an index page.
"""

from __future__ import annotations

import argparse
import ast
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

DEFAULT_SOURCE_FILENAMES: tuple[str, ...] = (
    "operators/geometry.py",
    "operators/transform.py",
    "operators/boolean.py",
    "operators/product.py",
    "operators/sketch.py",
    "operators/selection.py",
    "operators/features.py",
    "ql.py",
    "recording/serializer.py",
    "math.py",
    "product/placement.py",
    "product/material.py",
    "product/connector.py",
    "product/constraint.py",
    "product/part.py",
    "product/assembly.py",
    "product/solver.py",
    "params/expr.py",
    "params/tolerance.py",
    "params/units.py",
    "recording/graph.py",
    "sketch.py",
    "errors.py",
    "product/capture.py",
    "product/packages.py",
    "topology/model.py",
    "dxf_engine/model.py",
    "dxf_engine/planner.py",
    "dxf_engine/render.py",
    "build/assembly_builder.py",
    "build/dependencies.py",
    "build/part_builder.py",
    "build/results.py",
    "runtime/config.py",
    "runtime/executor.py",
    "runtime/runner.py",
    "inverse_engineer/brep/evaluation.py",
    "inspect/brep/compare.py",
    "inspect/brep/diagnostics.py",
    "inspect/brep/fitting.py",
    "inspect/brep/inspect.py",
    "inspect/brep/io.py",
    "inspect/brep/manufacturing.py",
    "inspect/brep/model.py",
    "inspect/brep/parity.py",
    "inspect/brep/persistence.py",
    "inspect/brep/queries.py",
    "inspect/brep/render.py",
    "inspect/brep/section_tracking.py",
    "inspect/brep/slices.py",
    "exporter/step.py",
    "exporter/obj.py",
    "exporter/stl.py",
    "exporter/mjcf.py",
    "inspect/brep/snapshots.py",
    "inspect/brep/topology_inspection.py",
    "inspect/drawing/calibrate.py",
    "inspect/drawing/geometry.py",
    "inspect/drawing/evidence.py",
    "inspect/drawing/preflight.py",
    "inspect/drawing/render.py",
    "inspect/drawing/section.py",
    "inspect/drawing/summary.py",
    "inspect/drawing/text.py",
)

DEFAULT_STDLIB_SOURCE_FILENAMES: tuple[str, ...] = (
    "std/bearing.py",
    "std/gear.py",
)

FULL_PUBLIC_FUNCTION_MODULES = frozenset(
    {
        "operators/geometry.py",
        "operators/transform.py",
        "operators/boolean.py",
        "operators/product.py",
        "operators/sketch.py",
        "operators/selection.py",
        "operators/features.py",
        "ql.py",
        "math.py",
        "product/placement.py",
    }
)

EXPORTED_FUNCTION_MODULES = frozenset(
    {
        "recording/serializer.py",
        "recording/graph.py",
        "params/expr.py",
        "params/tolerance.py",
        "params/units.py",
        "errors.py",
        "product/capture.py",
        "product/packages.py",
        "product/solver.py",
        "product/connector.py",
        "product/placement.py",
        "build/assembly_builder.py",
        "build/dependencies.py",
        "build/part_builder.py",
        "inverse_engineer/brep/evaluation.py",
        "inspect/brep/compare.py",
        "inspect/brep/diagnostics.py",
        "inspect/brep/fitting.py",
        "inspect/brep/inspect.py",
        "inspect/brep/io.py",
        "inspect/brep/manufacturing.py",
        "inspect/brep/model.py",
        "inspect/brep/parity.py",
        "inspect/brep/persistence.py",
        "inspect/brep/queries.py",
        "inspect/brep/render.py",
        "inspect/brep/section_tracking.py",
        "inspect/brep/slices.py",
        "exporter/step.py",
        "exporter/obj.py",
        "exporter/stl.py",
        "exporter/mjcf.py",
        "inspect/brep/snapshots.py",
        "inspect/brep/topology_inspection.py",
        "inspect/drawing/calibrate.py",
        "inspect/drawing/geometry.py",
        "inspect/drawing/evidence.py",
        "inspect/drawing/preflight.py",
        "inspect/drawing/render.py",
        "inspect/drawing/section.py",
        "inspect/drawing/summary.py",
        "inspect/drawing/text.py",
    }
)

EXPORTED_CALLABLE_MODULES = frozenset(
    {
        "params/expr.py",
        "params/tolerance.py",
        "params/units.py",
        "recording/graph.py",
        "sketch.py",
        "errors.py",
        "topology/model.py",
        "math.py",
        "product/placement.py",
        "product/material.py",
        "product/connector.py",
        "product/constraint.py",
        "product/part.py",
        "product/assembly.py",
    }
)

# The notebook runtime's public surface (``simplecadapi.runtime.__all__``
# minus the error types); ``use`` and ``notebook_id`` are also exported at
# the top level.
RUNTIME_EXPORTS = frozenset(
    {"CellReport", "NotebookConfig", "NotebookRun", "notebook_id", "run_notebook", "use"}
)

MISSING = object()


def _repo_root_from(module_file: Path | str | None = None) -> Path:
    target = Path(module_file) if module_file is not None else Path(__file__)
    repo_root = target.resolve().parents[1]
    if not (repo_root / "pyproject.toml").is_file():
        raise FileNotFoundError(f"project root not found above {target}")
    return repo_root


def _package_root_from(module_file: Path | str | None = None) -> Path:
    return _repo_root_from(module_file) / "src" / "simplecadapi"


def _default_source_files(package_root: Path) -> List[Path]:
    source_files = [package_root / name for name in DEFAULT_SOURCE_FILENAMES]
    translator_root = package_root / "translator"
    for backend_dir in sorted(translator_root.glob("*_translator")):
        source_files.extend([backend_dir / "api.py", backend_dir / "translator.py"])
        types_file = backend_dir / "types.py"
        if types_file.is_file():
            source_files.append(types_file)
    return source_files


def _translator_backend_name(module_name: str) -> str | None:
    parts = module_name.split("/")
    if (
        len(parts) == 3
        and parts[0] == "translator"
        and parts[1].endswith("_translator")
        and parts[2] in {"api.py", "translator.py", "types.py"}
    ):
        return parts[1]
    return None


def _default_stdlib_source_files(package_root: Path) -> List[Path]:
    return [package_root / name for name in DEFAULT_STDLIB_SOURCE_FILENAMES]


def _default_output_dirs(module_file: Path | str | None = None) -> List[Path]:
    return [_repo_root_from(module_file) / "docs/skill/references/docs/api"]


def _default_stdlib_output_dirs(module_file: Path | str | None = None) -> List[Path]:
    return [_repo_root_from(module_file) / "docs/skill/references/docs/stdlib"]


@dataclass
class ApiInfo:
    """Container for extracted API metadata."""

    name: str
    kind: str
    signature: str
    source_file: str
    parsed_doc: Dict[str, object]
    import_surface: str
    doc_filename: str = ""


class APIDocumentGenerator:
    """Generate markdown docs for API functions."""

    def __init__(
        self,
        source_files: Sequence[Path],
        output_dirs: Sequence[Path],
        clean_stale: bool = True,
        quiet: bool = False,
    ):
        self.source_files = list(source_files)
        self.output_dirs = list(output_dirs)
        self.clean_stale = clean_stale
        self.quiet = quiet
        self.apis: List[ApiInfo] = []
        self.exported_names = self._load_top_level_exports()

    def log(self, message: str) -> None:
        if not self.quiet:
            print(message)

    def extract_apis(self) -> List[ApiInfo]:
        """Extract supported public callables with docstrings."""
        self.log("正在分析源文件...")

        extracted: List[ApiInfo] = []
        exported_names = self.exported_names
        for file_path in self.source_files:
            if not file_path.exists():
                self.log(f"警告: 找不到文件 {file_path}，跳过。")
                continue

            self.log(f"  正在处理 {file_path}...")
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
            module_name = self._module_name_for(file_path)

            file_count = 0
            for node in tree.body:
                api_info = self._extract_api_info(node, module_name, exported_names)
                if api_info is None:
                    continue

                extracted.append(api_info)
                file_count += 1

            self.log(f"    从 {file_path.name} 提取到 {file_count} 个API")

        self.apis = self._assign_doc_filenames(extracted)
        self.log(f"成功总共提取到 {len(self.apis)} 个API")
        return self.apis

    def _module_name_for(self, file_path: Path) -> str:
        # Climb to the topmost package directory containing this file (the
        # highest ancestor still holding an __init__.py) and express the
        # module relative to it; fall back to the basename for loose files.
        current = file_path.parent
        topmost: Path | None = None
        while (current / "__init__.py").exists():
            topmost = current
            parent = current.parent
            if parent == current:
                break
            current = parent
        if topmost is not None:
            try:
                return file_path.resolve().relative_to(topmost.resolve()).as_posix()
            except ValueError:
                pass
        return file_path.name

    @staticmethod
    def _assign_doc_filenames(apis: List[ApiInfo]) -> List[ApiInfo]:
        counts: Dict[str, int] = {}
        assigned: List[ApiInfo] = []

        for api in apis:
            base = api.name
            lowered = base.lower()
            counts[lowered] = counts.get(lowered, 0) + 1
            if counts[lowered] == 1:
                filename = f"{base}.md"
            else:
                filename = f"{base}_{api.kind}.md"
            assigned.append(
                ApiInfo(
                    name=api.name,
                    kind=api.kind,
                    signature=api.signature,
                    source_file=api.source_file,
                    parsed_doc=api.parsed_doc,
                    import_surface=api.import_surface,
                    doc_filename=filename,
                )
            )

        return assigned

    def _extract_api_info(
        self,
        node: ast.stmt,
        module_name: str,
        exported_names: set[str],
    ) -> ApiInfo | None:
        if isinstance(node, ast.FunctionDef):
            if not self._should_include_function(
                node.name, module_name, exported_names
            ):
                return None

            docstring = ast.get_docstring(node)
            if not docstring:
                return None

            return ApiInfo(
                name=node.name,
                kind="function",
                signature=self._get_function_signature(node),
                source_file=module_name,
                parsed_doc=self._parse_docstring(docstring),
                import_surface=self._import_surface_for(node.name, module_name),
            )

        if isinstance(node, ast.ClassDef):
            if not self._should_include_class(node.name, module_name, exported_names):
                return None

            docstring = ast.get_docstring(node)
            if not docstring:
                return None

            return ApiInfo(
                name=node.name,
                kind="class",
                signature=self._get_class_signature(node),
                source_file=module_name,
                parsed_doc=self._parse_docstring(docstring),
                import_surface=self._import_surface_for(node.name, module_name),
            )

        return None

    @staticmethod
    def _should_include_function(
        name: str,
        module_name: str,
        exported_names: set[str],
    ) -> bool:
        if name.startswith("_"):
            return False
        if module_name.startswith("exporter/"):
            return True
        if name.startswith("_"):
            return False
        if module_name in FULL_PUBLIC_FUNCTION_MODULES:
            return True
        if _translator_backend_name(module_name) is not None:
            return True
        if module_name.startswith("inspect/brep/"):
            return name.endswith(
                (
                    "_rbrepcomparison",
                    "_rbrepinspection",
                    "_rbrepmodel",
                    "_rdescriptor",
                    "_rdescriptorlist",
                    "_rentityinspectionparity",
                    "_rinspectionsummarycomparison",
                    "_rnone",
                    "_rpath",
                    "_rshape",
                    "_rslicecomparison",
                    "_rslicespeclist",
                    "_rsummary",
                    "_rtuple",
                )
            )
        if module_name.startswith("inspect/drawing/"):
            return name.endswith(
                (
                    "_rcalibration",
                    "_rdimensions",
                    "_rmeasurements",
                    "_rpath",
                    "_rrecord",
                    "_rreport",
                    "_rstrokes",
                    "_rsummary",
                    "_rwords",
                    "_rverdict",
                )
            )
        if module_name == "inverse_engineer/brep/evaluation.py":
            return name in {
                "classify_benchmark_result",
                "inspect_benchmark_step",
                "run_comparison_bundle",
            }
        if module_name.startswith("dxf_engine/"):
            return name in {"render_plan"}
        if module_name.startswith("runtime/"):
            return name in RUNTIME_EXPORTS
        if module_name in EXPORTED_FUNCTION_MODULES:
            if not exported_names:
                return True
            return name in exported_names
        return False

    @staticmethod
    def _should_include_class(
        name: str,
        module_name: str,
        exported_names: set[str],
    ) -> bool:
        if name.startswith("_"):
            return False
        if module_name.startswith("exporter/"):
            return True
        if _translator_backend_name(module_name) is not None:
            return True
        if module_name.startswith("inspect/brep/"):
            return name in {
                "BRepComparison",
                "BRepEntityError",
                "BRepInspection",
                "BRepModel",
                "EntityInspectionParity",
                "InspectionSummaryComparison",
                "SliceComparison",
                "SlicePanelResult",
                "SliceSpec",
            }
        if module_name.startswith("inspect/drawing/"):
            return name in {
                "DrawingCalibration",
                "DrawingMeasurements",
                "DrawingSectionDimensions",
                "DrawingStrokes",
                "DrawingSummary",
                "DrawingText",
            }
        if module_name == "inverse_engineer/brep/evaluation.py":
            return name in {"EvaluationConfig", "SectionEvaluationConfig"}
        if module_name.startswith("runtime/"):
            return name in RUNTIME_EXPORTS
        if module_name.startswith("dxf_engine/"):
            return name in {
                "SheetDecl",
                "ViewDecl",
                "DimDecl",
                "DatumDecl",
                "CenterDecl",
                "LeaderDecl",
                "SheetPlan",
                "Resolved",
            }
        if name in exported_names:
            return True
        if module_name not in EXPORTED_CALLABLE_MODULES:
            return False
        if not exported_names:
            return True
        return name in exported_names

    def _load_top_level_exports(self) -> set[str]:
        init_file = self._find_top_level_init_file()
        if init_file is None or not init_file.exists():
            return set()

        tree = ast.parse(init_file.read_text(encoding="utf-8"), filename=str(init_file))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != "__all__":
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue

            exported: set[str] = set()
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    exported.add(item.value)
            return exported
        return set()

    def _import_surface_for(self, name: str, module_name: str) -> str:
        if module_name == "inverse_engineer/brep/evaluation.py":
            return (
                "reverse-engineering evaluator: `from simplecadapi.inverse_engineer.brep "
                f"import {name}`"
            )

        if name in self.exported_names:
            return f"top-level: `from simplecadapi import {name}`"

        if module_name.startswith("exporter/"):
            exporter_module = module_name.removeprefix("exporter/").removesuffix(".py")
            return (
                f"exporter namespace: `from simplecadapi import exporter` "
                f"then `exporter.{exporter_module}.{name}(...)`"
            )

        translator_backend = _translator_backend_name(module_name)
        if translator_backend is not None:
            return (
                "translator backend: "
                f"`from simplecadapi.translator.{translator_backend} import {name}`"
            )

        if module_name.startswith("inspect/brep/"):
            return (
                "inspection namespace: `from simplecadapi.inspect import brep` "
                f"then `brep.{name}(...)`; unavailable inside GraphSession"
            )

        if module_name.startswith("inspect/drawing/"):
            return (
                "drawing-inspection namespace: "
                "`from simplecadapi.inspect import drawing` "
                f"then `drawing.{name}(...)`; unavailable inside GraphSession"
            )

        if module_name.startswith("dxf_engine/"):
            return (
                "drawing namespace: "
                f"`from simplecadapi.dxf_engine import {name}`"
            )

        if module_name.startswith("runtime/"):
            return f"notebook runtime: `from simplecadapi.runtime import {name}`"

        module_stem = module_name.removesuffix(".py")
        if module_stem in {"field", "ql"}:
            return (
                f"submodule: `from simplecadapi.{module_stem} import {name}` "
                f"or `simplecadapi.{module_stem}.{name}`"
            )

        return f"submodule: `from simplecadapi.{module_stem} import {name}`"

    def _find_top_level_init_file(self) -> Path | None:
        # Climb from each source file to the topmost package directory (the
        # highest ancestor still holding an __init__.py); source files now
        # live in subpackages, so their immediate parent init is not the
        # top-level one.
        for source_file in self.source_files:
            current = source_file.parent
            topmost: Path | None = None
            while (current / "__init__.py").exists():
                topmost = current / "__init__.py"
                parent = current.parent
                if parent == current:
                    break
                current = parent
            if topmost is not None:
                return topmost
        return None

    def generate_markdown_docs(self) -> None:
        """Generate markdown docs for all configured output directories."""
        if not self.apis:
            self.log("没有可生成的API文档。")
            return

        for output_dir in self.output_dirs:
            self._generate_for_single_output_dir(output_dir)

    def _generate_for_single_output_dir(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"正在生成markdown文档到: {output_dir}")

        generated_files = set()
        created_or_updated = 0

        for api in sorted(self.apis, key=lambda item: item.name):
            filename = api.doc_filename or f"{api.name}.md"
            file_path = output_dir / filename
            md_content = self._build_single_api_markdown(api)
            changed = self._write_if_changed(file_path, md_content)
            if changed:
                created_or_updated += 1
            generated_files.add(filename)

        readme_path = output_dir / "README.md"
        readme_content = self._build_api_index_markdown()
        if self._write_if_changed(readme_path, readme_content):
            created_or_updated += 1

        removed_count = 0
        if self.clean_stale:
            removed_count = self._remove_stale_docs(output_dir, generated_files)

        self.log(
            f"文档生成完成: {output_dir} "
            f"(更新 {created_or_updated} 个文件, 删除 {removed_count} 个过期文档)"
        )

    def _build_single_api_markdown(self, api: ApiInfo) -> str:
        parsed = api.parsed_doc
        md_lines: List[str] = []
        definition_title = (
            "Class Definition" if api.kind == "class" else "API Definition"
        )

        md_lines.append(f"# {api.name}")
        md_lines.append("")

        md_lines.append(f"## {definition_title}")
        md_lines.append("")
        md_lines.append("```python")
        md_lines.append(api.signature)
        md_lines.append("```")
        md_lines.append("")
        md_lines.append(f"*Source: {api.source_file}*")
        md_lines.append("")

        md_lines.append("## Import Surface")
        md_lines.append("")
        md_lines.append(f"- {api.import_surface}")
        md_lines.append("")

        description = str(parsed.get("description", "")).strip()
        usage = str(parsed.get("usage", "")).strip()
        usage_parts = [part for part in [description, usage] if part]
        if usage_parts:
            merged_usage = "\n\n".join(dict.fromkeys(usage_parts))
            md_lines.append("## Description")
            md_lines.append("")
            md_lines.extend(merged_usage.splitlines())
            md_lines.append("")

        args = parsed.get("args", [])
        if isinstance(args, list) and args:
            md_lines.append("## Parameters")
            md_lines.append("")
            for arg in args:
                arg_name = str(arg.get("name", "")).strip()
                arg_type = str(arg.get("type", "")).strip()
                arg_desc = str(arg.get("description", "")).strip()

                md_lines.append(f"### {arg_name}")
                md_lines.append("")
                if arg_type:
                    md_lines.append(f"- **Type**: `{arg_type}`")
                md_lines.append(f"- **Description**: {arg_desc}")
                md_lines.append("")

        returns_text = str(parsed.get("returns", "")).strip()
        if returns_text:
            md_lines.append("## Returns")
            md_lines.append("")
            md_lines.extend(returns_text.splitlines())
            md_lines.append("")

        raises = parsed.get("raises", [])
        if isinstance(raises, list) and raises:
            md_lines.append("## Raises")
            md_lines.append("")
            for exc in raises:
                exc_type = str(exc.get("type", "")).strip()
                exc_desc = str(exc.get("description", "")).strip()
                md_lines.append(f"- **{exc_type}**: {exc_desc}")
            md_lines.append("")

        examples = parsed.get("examples", [])
        if isinstance(examples, list) and examples:
            md_lines.append("## Examples")
            md_lines.append("")
            for index, block in enumerate(examples, start=1):
                if len(examples) > 1:
                    md_lines.append(f"### Example {index}")
                md_lines.append("```python")
                md_lines.extend(block.splitlines())
                md_lines.append("```")
                md_lines.append("")

        return "\n".join(md_lines).rstrip() + "\n"

    def _build_api_index_markdown(self) -> str:
        categories: Dict[str, List[ApiInfo]] = {
            "Basic Creation": [],
            "Transforms": [],
            "3D Operations": [],
            "Tagging and Selection": [],
            "Boolean Operations": [],
            "Export": [],
            "Translator Backends": [],
            "Math Helpers": [],
            "Modeling Graph and Replay": [],
            "Expressions and Parameters": [],
            "Physical Units": [],
            "Types and Errors": [],
            "Advanced Features": [],
            "STEP/BREP Inspection": [],
            "Drawing Inspection": [],
            "Product Build": [],
            "Notebook Runtime": [],
            "Reconstruction Evaluation": [],
            "Engineering Drawings": [],
            "Other": [],
        }

        for api in self.apis:
            name = api.name

            if api.source_file.startswith("inspect/brep/"):
                categories["STEP/BREP Inspection"].append(api)
                continue
            if api.source_file.startswith("inspect/drawing/"):
                categories["Drawing Inspection"].append(api)
                continue
            if api.source_file.startswith("build/"):
                categories["Product Build"].append(api)
                continue
            if api.source_file.startswith("runtime/"):
                categories["Notebook Runtime"].append(api)
                continue

            if api.source_file == "inverse_engineer/brep/evaluation.py":
                categories["Reconstruction Evaluation"].append(api)
                continue

            if api.source_file.startswith("dxf_engine/"):
                categories["Engineering Drawings"].append(api)
                continue

            if api.source_file in {"recording/serializer.py", "recording/graph.py"}:
                categories["Modeling Graph and Replay"].append(api)
                continue

            if api.source_file.startswith("exporter/"):
                categories["Export"].append(api)
                continue
            if _translator_backend_name(api.source_file) is not None:
                categories["Translator Backends"].append(api)
                continue

            if api.source_file == "math.py":
                categories["Math Helpers"].append(api)
                continue

            if api.source_file in {"params/expr.py", "params/tolerance.py"}:
                categories["Expressions and Parameters"].append(api)
                continue

            if api.source_file == "params/units.py":
                categories["Physical Units"].append(api)
                continue

            if api.source_file in {"sketch.py", "errors.py"}:
                categories["Types and Errors"].append(api)
                continue

            if name.startswith("make_"):
                categories["Basic Creation"].append(api)
            elif name.startswith(("translate_", "rotate_", "mirror_")):
                categories["Transforms"].append(api)
            elif name.startswith(("extrude_", "revolve_", "loft_", "sweep_")):
                categories["3D Operations"].append(api)
            elif name.startswith(("apply_tag", "list_tags", "select_")):
                categories["Tagging and Selection"].append(api)
            elif name.startswith(("union_", "cut_", "intersect_")):
                categories["Boolean Operations"].append(api)
            elif name.startswith("export_"):
                categories["Export"].append(api)
            elif name.startswith(
                ("fillet_", "chamfer_", "shell_", "pattern_", "helical_")
            ):
                categories["Advanced Features"].append(api)
            else:
                categories["Other"].append(api)

        md_lines: List[str] = [
            "# SimpleCAD API Index",
            "",
            "This index includes generated docs for the public SimpleCAD API surface, including geometry operations, graph/model JSON workflows, durable product builds, the notebook runtime, inspection tools, expressions, QL, and export helpers.",
            "",
            "## Import Surfaces",
            "",
            "- Entries marked `top-level` are exported from `simplecadapi` and can be imported with `from simplecadapi import <name>`.",
            "- Entries marked `submodule` are public through the listed submodule, such as `simplecadapi.ql`.",
            "- Entries marked `inspection namespace` are available through `simplecadapi.inspect.brep` and cannot run inside `GraphSession`.",
            "- Entries marked `drawing-inspection namespace` are available through `simplecadapi.inspect.drawing` and cannot run inside `GraphSession`.",
            "- Entries marked `translator backend` are public only through `simplecadapi.translator.<backend>`.",
            "- Entries marked `reverse-engineering evaluator` are available through `simplecadapi.inverse_engineer.brep`; their acceptance inputs and reports belong to the trusted harness, not participant code.",
            "",
        ]

        for category, api_list in categories.items():
            if not api_list:
                continue
            md_lines.append(f"## {category}")
            md_lines.append("")
            for api in sorted(api_list, key=lambda item: item.name):
                source_info = f" *(from {api.source_file})*"
                if api.name in self.exported_names:
                    surface_info = " `top-level`"
                elif api.source_file.startswith("inspect/brep/"):
                    surface_info = " `inspection namespace`"
                elif api.source_file.startswith("inspect/drawing/"):
                    surface_info = " `drawing-inspection namespace`"
                elif api.source_file.startswith("exporter/"):
                    surface_info = " `exporter namespace`"
                elif api.source_file.startswith("translator/"):
                    surface_info = " `translator backend`"
                elif api.source_file == "inverse_engineer/brep/evaluation.py":
                    surface_info = " `reverse-engineering evaluator`"
                elif api.source_file.startswith("runtime/"):
                    surface_info = " `notebook runtime`"
                else:
                    surface_info = f" `submodule:{api.source_file.removesuffix('.py')}`"
                doc_filename = api.doc_filename or f"{api.name}.md"
                md_lines.append(
                    f"- [{api.name}]({doc_filename}){source_info}{surface_info}"
                )
            md_lines.append("")

        return "\n".join(md_lines).rstrip() + "\n"

    def _remove_stale_docs(self, output_dir: Path, generated_files: set[str]) -> int:
        removed = 0
        keep = set(generated_files)
        keep.add("README.md")

        for path in output_dir.glob("*.md"):
            if path.name in keep:
                continue
            path.unlink()
            removed += 1

        return removed

    @staticmethod
    def _write_if_changed(file_path: Path, content: str) -> bool:
        if file_path.exists() and file_path.read_text(encoding="utf-8") == content:
            return False
        file_path.write_text(content, encoding="utf-8")
        return True

    def _parse_docstring(self, docstring: str) -> Dict[str, object]:
        sections = {
            "description": [],
            "args": [],
            "returns": [],
            "raises": [],
            "usage": [],
            "examples": [],
        }

        current_section = "description"
        for raw_line in docstring.splitlines():
            stripped = raw_line.strip()

            next_section = self._map_section_header(stripped)
            if next_section:
                current_section = next_section
                continue

            sections[current_section].append(raw_line.rstrip())

        parsed: Dict[str, object] = {
            "description": self._collapse_paragraph_lines(sections["description"]),
            "args": self._parse_args_section(sections["args"]),
            "returns": self._collapse_paragraph_lines(sections["returns"]),
            "raises": self._parse_raises_section(sections["raises"]),
            "usage": self._collapse_paragraph_lines(sections["usage"]),
            "examples": self._parse_examples_section(sections["examples"]),
        }
        return parsed

    @staticmethod
    def _map_section_header(stripped_line: str) -> str | None:
        normalized = stripped_line.rstrip(":").strip().lower()
        if normalized in {"args", "argument", "arguments", "parameters", "params"}:
            return "args"
        if normalized in {"returns", "return"}:
            return "returns"
        if normalized in {"raises", "raise", "exceptions", "exception"}:
            return "raises"
        if normalized in {"usage", "how to use"}:
            return "usage"
        if normalized in {"example", "examples"}:
            return "examples"
        return None

    @staticmethod
    def _collapse_paragraph_lines(lines: Iterable[str]) -> str:
        filtered: List[str] = []
        previous_blank = False
        for line in lines:
            text = line.strip()
            if not text:
                if not previous_blank:
                    filtered.append("")
                previous_blank = True
                continue
            filtered.append(text)
            previous_blank = False
        return "\n".join(filtered).strip()

    def _parse_args_section(self, lines: Iterable[str]) -> List[Dict[str, str]]:
        args: List[Dict[str, str]] = []
        current: Dict[str, str] | None = None

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue

            if ":" in stripped and not stripped.startswith(("-", "* ")):
                if current:
                    args.append(current)

                left, right = stripped.split(":", 1)
                left = left.strip()
                description = right.strip()

                if not left:
                    if current:
                        current["description"] = (
                            f"{current['description']} {stripped}".strip()
                        )
                    continue

                name = left
                type_info = ""
                if "(" in left and ")" in left and left.endswith(")"):
                    open_index = left.rfind("(")
                    close_index = left.rfind(")")
                    if open_index < close_index:
                        name = left[:open_index].strip()
                        type_info = left[open_index + 1 : close_index].strip()
                elif self._looks_like_type_annotation(description):
                    type_info = description
                    description = ""

                current = {"name": name, "type": type_info, "description": description}
                continue

            if current:
                current["description"] = f"{current['description']} {stripped}".strip()

        if current:
            args.append(current)

        return args

    @staticmethod
    def _looks_like_type_annotation(text: str) -> bool:
        stripped = text.strip()
        if not stripped or stripped.endswith("."):
            return False

        first = stripped.split(",", 1)[0].strip()
        first_word = first.split()[0] if first else ""
        return first_word.startswith(
            (
                "int",
                "float",
                "str",
                "bool",
                "tuple",
                "list",
                "dict",
                "Sequence",
                "Iterable",
                "Optional",
                "Solid",
                "Face",
                "Wire",
                "Edge",
                "Vertex",
                "Placement",
                "Part",
                "Assembly",
            )
        )

    def _parse_raises_section(self, lines: Iterable[str]) -> List[Dict[str, str]]:
        raises: List[Dict[str, str]] = []
        current: Dict[str, str] | None = None

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue

            if ":" in stripped and not stripped.startswith(("-", "* ")):
                if current:
                    raises.append(current)
                exc_name, exc_desc = stripped.split(":", 1)
                current = {"type": exc_name.strip(), "description": exc_desc.strip()}
                continue

            if current:
                current["description"] = f"{current['description']} {stripped}".strip()

        if current:
            raises.append(current)

        return raises

    @staticmethod
    def _parse_examples_section(lines: Iterable[str]) -> List[str]:
        blocks: List[str] = []
        current: List[str] = []

        for raw_line in lines:
            if raw_line.strip() == "":
                if current:
                    blocks.append(
                        APIDocumentGenerator._normalize_example_block(current)
                    )
                    current = []
                continue
            current.append(raw_line)

        if current:
            blocks.append(APIDocumentGenerator._normalize_example_block(current))

        return [block for block in blocks if block.strip()]

    @staticmethod
    def _normalize_example_block(lines: List[str]) -> str:
        while lines and not lines[0].strip():
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines = lines[:-1]
        if not lines:
            return ""
        return textwrap.dedent("\n".join(lines)).strip("\n")

    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        params: List[str] = []

        positional = list(node.args.posonlyargs) + list(node.args.args)
        padded_defaults = [MISSING] * (
            len(positional) - len(node.args.defaults)
        ) + list(node.args.defaults)

        for arg, default in zip(positional, padded_defaults):
            params.append(self._format_arg(arg, default))

        if node.args.posonlyargs:
            params.insert(len(node.args.posonlyargs), "/")

        if node.args.vararg:
            params.append(f"*{self._format_arg(node.args.vararg)}")
        elif node.args.kwonlyargs:
            params.append("*")

        for kw_arg, kw_default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            default = kw_default if kw_default is not None else MISSING
            params.append(self._format_arg(kw_arg, default))

        if node.args.kwarg:
            params.append(f"**{self._format_arg(node.args.kwarg)}")

        returns = ""
        if node.returns is not None:
            returns = f" -> {self._safe_unparse(node.returns)}"

        return f"def {node.name}({', '.join(params)}){returns}"

    def _get_class_signature(self, node: ast.ClassDef) -> str:
        init_method: ast.FunctionDef | None = None
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                init_method = item
                break

        if init_method is None:
            dataclass_fields = self._extract_dataclass_fields(node)
            if dataclass_fields:
                params = ", ".join(dataclass_fields)
                return f"class {node.name}({params})"
            return f"class {node.name}"

        params: List[str] = []

        positional = list(init_method.args.posonlyargs) + list(init_method.args.args)
        if positional and positional[0].arg == "self":
            positional = positional[1:]
        padded_defaults = [MISSING] * (
            len(positional) - len(init_method.args.defaults)
        ) + list(init_method.args.defaults)

        for arg, default in zip(positional, padded_defaults):
            params.append(self._format_arg(arg, default))

        if init_method.args.posonlyargs:
            visible_posonly_count = len(init_method.args.posonlyargs)
            if init_method.args.args and init_method.args.args[0].arg == "self":
                visible_posonly_count = max(0, visible_posonly_count - 1)
            if visible_posonly_count > 0:
                params.insert(visible_posonly_count, "/")

        if init_method.args.vararg:
            params.append(f"*{self._format_arg(init_method.args.vararg)}")
        elif init_method.args.kwonlyargs:
            params.append("*")

        for kw_arg, kw_default in zip(
            init_method.args.kwonlyargs, init_method.args.kw_defaults
        ):
            default = kw_default if kw_default is not None else MISSING
            params.append(self._format_arg(kw_arg, default))

        if init_method.args.kwarg:
            params.append(f"**{self._format_arg(init_method.args.kwarg)}")

        return f"class {node.name}({', '.join(params)})"

    def _format_arg(self, arg: ast.arg, default: object = MISSING) -> str:
        text = arg.arg
        if arg.annotation is not None:
            text += f": {self._safe_unparse(arg.annotation)}"
        if default is not MISSING:
            text += f" = {self._safe_unparse(default)}"
        return text

    @staticmethod
    def _safe_unparse(node: ast.AST | object) -> str:
        if not isinstance(node, ast.AST):
            return "..."
        try:
            return ast.unparse(node)
        except Exception:
            return "..."

    def _extract_dataclass_fields(self, node: ast.ClassDef) -> List[str]:
        """Extract field signatures from a @dataclass class body.

        Looks for AnnAssign nodes (annotated assignments) at class scope,
        which is how dataclass fields are declared. Skips private fields
        (names starting with ``_``) since they are not part of the public
        constructor signature.
        """
        is_dataclass = any(
            isinstance(dec, ast.Name)
            and dec.id == "dataclass"
            or isinstance(dec, ast.Attribute)
            and dec.attr == "dataclass"
            or isinstance(dec, ast.Call)
            and (
                (isinstance(dec.func, ast.Name) and dec.func.id == "dataclass")
                or (
                    isinstance(dec.func, ast.Attribute) and dec.func.attr == "dataclass"
                )
            )
            for dec in node.decorator_list
        )
        if not is_dataclass:
            return []

        fields: List[str] = []
        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue
            name = item.target.id
            if name.startswith("_"):
                continue
            annotation = ""
            if item.annotation is not None:
                annotation = f": {self._safe_unparse(item.annotation)}"
            default = ""
            if item.value is not None:
                default = f" = {self._safe_unparse(item.value)}"
            fields.append(f"{name}{annotation}{default}")
        return fields


class StdlibDocumentGenerator(APIDocumentGenerator):
    """Generate markdown docs for standard-library part factories."""

    def _module_name_for(self, file_path: Path) -> str:
        if file_path.parent.name == "std":
            return f"std/{file_path.name}"
        return file_path.name

    @staticmethod
    def _should_include_function(
        name: str,
        module_name: str,
        exported_names: set[str],
    ) -> bool:
        return not name.startswith("_")

    @staticmethod
    def _should_include_class(
        name: str,
        module_name: str,
        exported_names: set[str],
    ) -> bool:
        return False

    def _import_surface_for(self, name: str, module_name: str) -> str:
        if module_name == "std/bearing.py":
            return (
                "standard library: `import simplecadapi as scad` then "
                f"`scad.std.bearing.{name}(...)`; direct submodule import: "
                f"`from simplecadapi.std.bearing import {name}`"
            )
        if module_name == "std/gear.py":
            return (
                "standard library: `import simplecadapi as scad` then "
                f"`scad.std.gear.{name}(...)`; direct submodule import: "
                f"`from simplecadapi.std.gear import {name}`"
            )

        module_stem = module_name.removesuffix(".py").replace("/", ".")
        return f"standard library: `from simplecadapi.{module_stem} import {name}`"

    def _build_api_index_markdown(self) -> str:
        categories: Dict[str, List[ApiInfo]] = {
            "Bearing Assemblies": [],
            "External Gears": [],
            "Internal Ring Gears": [],
            "Cycloidal Reducer Discs": [],
            "Racks": [],
            "Other Standard Parts": [],
        }

        for api in self.apis:
            name = api.name
            if api.source_file == "std/bearing.py":
                categories["Bearing Assemblies"].append(api)
            elif "cycloidal_disc" in name:
                categories["Cycloidal Reducer Discs"].append(api)
            elif "_ring_gear_" in name:
                categories["Internal Ring Gears"].append(api)
            elif "_rack_" in name:
                categories["Racks"].append(api)
            elif "_gear_" in name:
                categories["External Gears"].append(api)
            else:
                categories["Other Standard Parts"].append(api)

        md_lines: List[str] = [
            "# SimpleCAD Standard Library Index",
            "",
            "This index includes generated docs for standard part factory functions. Use these functions first when a task needs a standard mechanical part and does not require complex custom geometry changes.",
            "",
            "## Import Surfaces",
            "",
            "- Recommended package-level module export: `import simplecadapi as scad`, then call functions through submodules such as `scad.std.gear.<function>(...)` and `scad.std.bearing.<function>(...)`.",
            "- Direct submodule import is also supported, for example `from simplecadapi.std.gear import make_spur_gear_rsolid` or `from simplecadapi.std.bearing import make_ball_bearing_rassembly`.",
            "",
            "## Usage Guidance",
            "",
            "- Prefer standard-library factories for standard bearings, gears, ring gears, and racks before hand-modeling profiles with core geometry APIs.",
            "- Standard parts return normal SimpleCAD shapes or product assemblies, so they can be transformed, tagged, assembled, exported, or combined with core geometry operations.",
            "- Switch to core geometry APIs only when the requested standard part needs substantial custom geometry beyond the factory parameters.",
            "",
        ]

        for category, api_list in categories.items():
            if not api_list:
                continue
            md_lines.append(f"## {category}")
            md_lines.append("")
            for api in sorted(api_list, key=lambda item: item.name):
                doc_filename = api.doc_filename or f"{api.name}.md"
                md_lines.append(
                    f"- [{api.name}]({doc_filename}) *(from {api.source_file})* `stdlib`"
                )
            md_lines.append("")

        return "\n".join(md_lines).rstrip() + "\n"


def _parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SimpleCAD API markdown docs generator"
    )
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        help="Source file path. Can be provided multiple times.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dirs",
        action="append",
        help="Output directory path. Can be provided multiple times.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Keep stale markdown API docs instead of deleting them.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce console output.",
    )
    return parser.parse_args()


def _resolve_source_files(
    cli_sources: Sequence[str] | None,
    module_file: Path | str | None = None,
) -> List[Path]:
    if cli_sources:
        return [Path(item).resolve() for item in cli_sources]
    package_root = _package_root_from(module_file)
    return [path.resolve() for path in _default_source_files(package_root)]


def _resolve_output_dirs(
    cli_output_dirs: Sequence[str] | None,
    module_file: Path | str | None = None,
) -> List[Path]:
    if cli_output_dirs:
        return [Path(item).resolve() for item in cli_output_dirs]
    return [path.resolve() for path in _default_output_dirs(module_file)]


def _resolve_stdlib_source_files(
    cli_sources: Sequence[str] | None,
    module_file: Path | str | None = None,
) -> List[Path]:
    if cli_sources:
        return [Path(item).resolve() for item in cli_sources]
    package_root = _package_root_from(module_file)
    return [path.resolve() for path in _default_stdlib_source_files(package_root)]


def _resolve_stdlib_output_dirs(
    cli_output_dirs: Sequence[str] | None,
    module_file: Path | str | None = None,
) -> List[Path]:
    if cli_output_dirs:
        return [Path(item).resolve() for item in cli_output_dirs]
    return [path.resolve() for path in _default_stdlib_output_dirs(module_file)]


def main() -> None:
    args = _parse_cli_args()
    source_files = _resolve_source_files(args.sources)
    output_dirs = _resolve_output_dirs(args.output_dirs)
    generate_default_stdlib_docs = not args.sources and not args.output_dirs

    generator = APIDocumentGenerator(
        source_files=source_files,
        output_dirs=output_dirs,
        clean_stale=not args.no_clean,
        quiet=args.quiet,
    )

    apis = generator.extract_apis()
    if not apis:
        print("没有找到任何带有docstring的API函数")
        return

    generator.generate_markdown_docs()

    stdlib_api_count = 0
    if generate_default_stdlib_docs:
        stdlib_generator = StdlibDocumentGenerator(
            source_files=_resolve_stdlib_source_files(None),
            output_dirs=_resolve_stdlib_output_dirs(None),
            clean_stale=not args.no_clean,
            quiet=args.quiet,
        )
        stdlib_apis = stdlib_generator.extract_apis()
        stdlib_api_count = len(stdlib_apis)
        if stdlib_apis:
            stdlib_generator.generate_markdown_docs()

    if not args.quiet:
        print("\n✅ 文档生成完成！")
        print(f"📄 共处理 {len(apis)} 个API")
        if generate_default_stdlib_docs:
            print(f"📦 共处理 {stdlib_api_count} 个标准库API")
        print("📁 输出目录:")
        for path in output_dirs:
            print(f"  - {path}")
        if generate_default_stdlib_docs:
            for path in _resolve_stdlib_output_dirs(None):
                print(f"  - {path}")


if __name__ == "__main__":
    main()
