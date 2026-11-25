"""Command-line entry for the single-part drawing workflow."""

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys


def configure(subparsers):
    parser = subparsers.add_parser(
        "drawing", help="Plan or export a single-part DXF drawing"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--step", type=Path, help="Single-part STEP")
    source.add_argument(
        "--notebook", type=Path, help="Run a trusted SimpleCADAPI part notebook"
    )
    parser.add_argument("--out", type=Path, help="Output .dxf path")
    parser.add_argument(
        "--mode", choices=("auto", "engineering", "inspection"), default="auto"
    )
    parser.add_argument(
        "--templates", action="store_true", help="List drafting templates"
    )
    parser.add_argument(
        "--drawing-json", type=Path, help="Replay a declarative engineering drawing"
    )
    parser.add_argument("--template", help="Drafting template ID")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Notebook parameter override",
    )
    parser.add_argument(
        "--plan-only", action="store_true", help="Write the plan and declaration only"
    )
    parser.add_argument(
        "--pdf", action="store_true", help="Also write a true-scale vector PDF"
    )
    parser.add_argument("--sheet", choices=("A4", "A3", "A2", "A1", "A0"))
    parser.add_argument("--projection", choices=("first", "third"))
    parser.add_argument("--layout", choices=("aligned", "compact"))
    parser.add_argument("--no-section", action="store_true")
    parser.add_argument("--section-view", choices=("full", "removed"))
    parser.add_argument(
        "--primary-view", choices=("front", "rear", "top", "bottom", "left", "right")
    )
    parser.add_argument("--dimensions", choices=("auto", "overall", "none"))
    parser.add_argument(
        "--hlr",
        choices=("auto", "exact", "polygonal"),
        help="Polygonal HLR requires the verify extra",
    )
    parser.add_argument(
        "--layout-json", type=Path, help="Shared seven-view inspection layout"
    )
    parser.add_argument(
        "--transform-json", type=Path, help="Explicit rigid placement of a STEP"
    )
    parser.add_argument(
        "--deflection", type=float, help="Inspection curve chordal deflection in mm"
    )
    parser.set_defaults(handler=handle, printer=print_json)


def print_json(report):
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))


def _read(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path else None


def _validate(args):
    if (
        args.out is None
        or args.out.suffix.lower() != ".dxf"
        or not (args.step or args.notebook)
    ):
        raise ValueError("Use --step or --notebook with --out <drawing.dxf>")
    reserved = {
        args.out.resolve().with_suffix(ext)
        for ext in (
            ".dxf",
            ".png",
            ".svg",
            ".pdf",
            ".json",
            ".txt",
            ".drawing.json",
            ".plan.json",
            ".model.step",
        )
    }
    if any(
        p and p.resolve() in reserved
        for p in (
            args.step,
            args.notebook,
            args.drawing_json,
            args.transform_json,
            args.layout_json,
        )
    ):
        raise ValueError("Choose an output stem distinct from the inputs")
    if args.set and not args.notebook:
        raise ValueError("--set requires --notebook")
    if args.notebook and (args.mode != "auto" or args.transform_json):
        raise ValueError("--notebook requires auto mode and uses notebook coordinates")
    if args.plan_only and args.pdf:
        raise ValueError("--plan-only cannot emit PDF")
    if args.mode != "auto" and any(
        (
            args.plan_only,
            args.template,
            args.sheet,
            args.primary_view,
            args.dimensions,
            args.layout,
            args.section_view,
            args.hlr,
            args.no_section,
        )
    ):
        raise ValueError("Automatic drawing options require --mode auto")
    if args.mode != "inspection" and (args.layout_json or args.deflection is not None):
        raise ValueError(
            "Shared layout and deflection options require --mode inspection"
        )
    if args.mode == "engineering" and (not args.drawing_json or args.projection):
        raise ValueError(
            "Engineering mode requires --drawing-json and reads projection from the declaration"
        )
    if args.mode != "engineering" and args.drawing_json:
        raise ValueError("--drawing-json requires --mode engineering")
    if args.mode == "inspection" and args.pdf:
        raise ValueError("--pdf requires an engineering drawing mode")


def handle(args):
    try:
        from .inspection import drawing_templates

        if args.templates:
            return drawing_templates(), 0
        _validate(args)
        with redirect_stdout(sys.stderr):
            result = _draw(args)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}, 2
    return result, int(result.get("status") == "needs_revision" and not args.plan_only)


def _draw(args):
    transform = _read(args.transform_json)
    if args.mode == "inspection":
        from .inspection import export_sheet, project_step

        project = project_step(
            args.step,
            transform=transform,
            deflection=0.03 if args.deflection is None else args.deflection,
        )
        result = export_sheet(
            project,
            args.out,
            layout=_read(args.layout_json),
            projection=args.projection or "first",
        )
        return {
            "dxf": str(args.out.resolve()),
            "views": len(project["views"]),
            "audit": result["reopen_audit"],
        }
    if args.mode == "engineering":
        from .declaration import export_engineering_sheet

        meta = export_engineering_sheet(
            args.step,
            args.out,
            _read(args.drawing_json),
            transform=transform,
            pdf=args.pdf,
        )
        return {
            "dxf": meta["output_dxf"],
            "views": meta["views"],
            "dimensions": meta["dimensions"],
            "issues": meta["issues"],
            "audit": meta["reopen_audit"],
        }

    from .auto import auto_drawing

    step, intent = args.step, None
    if args.notebook:
        from .notebook import overrides_from_args, prepare_notebook

        step = args.out.resolve().with_suffix(".model.step")
        intent = prepare_notebook(
            args.notebook.resolve(), step, overrides_from_args(args.set)
        )
    dimensions = args.dimensions or (
        "overall" if intent and intent["dimensions"] else "auto"
    )
    result = auto_drawing(
        step,
        args.out,
        primary=args.primary_view,
        sheet=args.sheet,
        section=not args.no_section,
        dimensions=dimensions,
        projection=args.projection,
        layout=args.layout,
        section_view=args.section_view,
        template=args.template,
        plan_only=args.plan_only,
        transform=transform,
        pdf=args.pdf,
        hlr=args.hlr or "auto",
        design_intent=intent,
    )
    if args.notebook:
        result["model_step"] = str(step)
    return result
