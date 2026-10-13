"""Isolated CAD worker; communicates only through an explicit JSON file."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import shutil
import traceback
import uuid


def _volume(shape):
    if not _solid_count(shape):
        from OCP.TopAbs import TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        if TopExp_Explorer(shape, TopAbs_FACE).More():
            raise ValueError("volume result has faces but no closed solid")
        return 0.0
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    properties = GProp_GProps()
    error = BRepGProp.VolumePropertiesGK_s(shape, properties, 1e-9, True, True)
    if error < 0:
        raise ValueError("Gauss-Kronrod volume integration failed")
    return float(properties.Mass())


def _area(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.GeomAbs import GeomAbs_C1
    from OCP.GProp import GProp_GProps
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideContinuity
    # Integration must respect C0 knot boundaries. Work on independent geometry
    # so this numerical conditioning never changes the FTC or exported STEP.
    copied = BRepBuilderAPI_Copy(shape, True, False).Shape()
    divide = ShapeUpgrade_ShapeDivideContinuity(copied)
    divide.SetSurfaceCriterion(GeomAbs_C1)
    divide.SetBoundaryCriterion(GeomAbs_C1)
    divide.SetPCurveCriterion(GeomAbs_C1)
    divide.Perform()
    measurement = divide.Result()
    if measurement.IsNull():
        raise ValueError("surface integration continuity split produced no shape")
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(S=measurement, SProps=properties, Eps=1e-10, SkipShared=False)
    return float(properties.Mass())


def _solid_count(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _read_step(step):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    if not step.is_file():
        raise FileNotFoundError(f"reference STEP does not exist: {step}")
    reader = STEPControl_Reader()
    if reader.ReadFile(str(step)) != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise ValueError("reference STEP could not be read")
    reference = reader.OneShape()
    if reference.IsNull() or not BRepCheck_Analyzer(reference).IsValid() or not _solid_count(reference):
        raise ValueError("reference STEP contains no valid solids")
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_OUT
    from OCP.TopExp import TopExp_Explorer
    explorer = TopExp_Explorer(reference, TopAbs_SOLID)
    while explorer.More():
        classifier = BRepClass3d_SolidClassifier(explorer.Current())
        classifier.PerformInfinitePoint(1e-7)
        if classifier.State() != TopAbs_OUT:
            raise ValueError("reference STEP solid orientation includes the infinite exterior")
        explorer.Next()
    return reference


def _compare_reference(shapes, step):
    return _compare_shapes(shapes, _read_step(step))


def _compare_shapes(shapes, reference):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.BRepCheck import BRepCheck_Analyzer
    # Treat body groups as a geometric set. Fuse disjoint bodies too, avoiding double
    # counting overlap when comparing a multi-body result to STEP assemblies.
    actual = shapes[0]
    for shape in shapes[1:]:
        fusion = BRepAlgoAPI_Fuse(actual, shape)
        fusion.Build()
        if not fusion.IsDone():
            raise ValueError("could not combine actual bodies for comparison")
        actual = fusion.Shape()
    tolerance = _kernel_tolerance(actual, reference)
    # Configure before the first Build: the two-shape constructor would already
    # run the intersection and retain a pave filler computed at default tolerance.
    missing = _cut(reference, actual, tolerance)
    extra = _cut(actual, reference, tolerance)
    for operation in (missing, extra):
        if not operation.IsDone() or operation.Shape().IsNull():
            return {"reference_status": "error", "reference_error": "STEP symmetric difference failed",
                    "reference_boolean_fuzzy_tolerance": tolerance}
        if not BRepCheck_Analyzer(operation.Shape()).IsValid():
            return {"reference_status": "error", "reference_error": "STEP symmetric difference produced invalid topology",
                    "reference_boolean_fuzzy_tolerance": tolerance}
    return {"reference_status": "ok", "reference_volume": _volume(reference),
            "reference_boolean_fuzzy_tolerance": tolerance,
            "symmetric_difference_volume": abs(_volume(missing.Shape())) + abs(_volume(extra.Shape()))}


def _cut(left, right, tolerance):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    try:
        from OCP.TopTools import TopTools_ListOfShape as ShapeList
    except ImportError:
        from OCP.collections import List_TopoDS_Shape as ShapeList
    arguments, tools = ShapeList(), ShapeList()
    arguments.Append(left)
    tools.Append(right)
    operation = BRepAlgoAPI_Cut()
    operation.SetArguments(arguments)
    operation.SetTools(tools)
    operation.SetNonDestructive(True)
    operation.SetFuzzyValue(tolerance)
    operation.Build()
    return operation


def _kernel_tolerance(*shapes):
    from OCP.BRep import BRep_Tool
    from OCP.Precision import Precision
    from OCP.TopAbs import TopAbs_VERTEX, TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    tolerance = float(Precision.Confusion_s())
    for shape in shapes:
        for kind, name in ((TopAbs_VERTEX, "Vertex"), (TopAbs_EDGE, "Edge")):
            cast = getattr(TopoDS, name + "_s", None) or getattr(TopoDS, name)
            explorer = TopExp_Explorer(shape, kind)
            while explorer.More():
                value = float(BRep_Tool.Tolerance_s(cast(explorer.Current())))
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid reference geometry tolerance")
                tolerance = max(tolerance, value)
                explorer.Next()
    return tolerance


def _export_step(shapes, path, options=None):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone
    writer = STEPControl_Writer()
    options = options or {}
    pcurves = options.get("write_pcurves", True)
    precision = options.get("precision_mode", "AVERAGE")
    modes = {"AVERAGE": 0, "GREATEST": 1, "LEAST": -1, "SESSION": 2}
    if not isinstance(pcurves, bool) or precision not in modes:
        raise ValueError("invalid source STEP export options")
    # Honor the declared corpus export contract: spherical seams retain their
    # UV curves; freeform sweeps can explicitly request rebuilding on import.
    if not Interface_Static.SetIVal_s("write.surfacecurve.mode", int(pcurves)):
        raise ValueError("could not configure STEP parameter-curve export")
    if not Interface_Static.SetIVal_s("write.precision.mode", modes[precision]):
        raise ValueError("could not configure STEP precision mode")
    for shape in shapes:
        if writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone:
            raise ValueError("could not transfer actual geometry for external comparison")
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise ValueError("could not export actual geometry for external comparison")
    return {"write_pcurves": pcurves, "precision_mode": precision,
            "rebuild_pcurves_on_import": not pcurves}


def _returned_shapes(value, placement=None):
    """Extract world-space topology from the actual build result."""
    from simplecadapi import Solid, Part, Assembly, PartBuildResult, AssemblyBuildResult
    from simplecadapi.product.placement import identity_placement
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    if isinstance(value, (PartBuildResult, AssemblyBuildResult)):
        value = value.value
    if isinstance(value, Part):
        value = value.body
    if isinstance(value, Assembly):
        parent = placement or identity_placement()
        return [shape for component in value.components
                for shape in _returned_shapes(component.item, parent.compose(component.placement))]
    if isinstance(value, Solid):
        if placement is None or placement == identity_placement():
            return [value.wrapped]
        x, y, z, o = placement.x_axis, placement.y_axis, placement.z_axis, placement.origin
        transform = gp_Trsf()
        transform.SetValues(x[0], y[0], z[0], o[0], x[1], y[1], z[1], o[1], x[2], y[2], z[2], o[2])
        return [BRepBuilderAPI_Transform(value.wrapped, transform, True).Shape()]
    raise ValueError("build() must return an actual Solid, Part or Assembly build result")


def run(ftc_path, staging_dir, reference_step=None, export_step=None, export_options=None):
    import OCP
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopoDS import TopoDS_Shape
    # An isolated path keeps imports/artifacts away from original outputs and
    # provides a fresh module/global BODIES namespace on every validation.
    staged = staging_dir / (ftc_path.stem + "_" + uuid.uuid4().hex + ".py")
    shutil.copyfile(ftc_path, staged)
    spec = importlib.util.spec_from_file_location("ftc_validation_" + uuid.uuid4().hex, staged)
    if spec is None or spec.loader is None:
        raise ValueError("cannot import FTC module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = getattr(module, "build", None)
    if not callable(build):
        raise ValueError("FTC module must define callable build()")
    built = build()
    bodies = getattr(module, "BODIES", None)
    if not isinstance(bodies, (list, tuple)) or not bodies:
        return {"status": "ok", "body_count": 0, "solid_count": 0,
                "is_valid": False, "volume": None, "bbox": None}
    for index, body in enumerate(bodies):
        wrapped = getattr(body, "wrapped", None)
        if not isinstance(wrapped, TopoDS_Shape) or wrapped.IsNull():
            raise ValueError(f"BODIES[{index}] is not actual nonempty CAD topology")
        if _solid_count(wrapped) < 1:
            raise ValueError(f"BODIES[{index}] contains no solid")
    shapes = _returned_shapes(built)
    if not shapes or len(shapes) != len(bodies):
        raise ValueError("build() result body count does not match BODIES")
    if any(shape.IsNull() or not _solid_count(shape) for shape in shapes):
        raise ValueError("build() returned empty CAD topology")
    if not all(body.wrapped.IsSame(shape) for body, shape in zip(bodies, shapes)):
        from simplecadapi.kernel.ocp_export import make_compound_always
        consistency = _compare_shapes(shapes, make_compound_always([body.wrapped for body in bodies]))
        if (consistency["reference_status"] != "ok" or
                consistency["symmetric_difference_volume"] > max(1e-7, abs(consistency["reference_volume"]) * 1e-7)):
            raise ValueError("BODIES geometry does not match the actual build() result")
    bounds = Bnd_Box()
    for shape in shapes:
        BRepBndLib.AddOptimal_s(shape, bounds, False, False)
    volume = sum(_volume(shape) for shape in shapes)
    low, high = bounds.CornerMin(), bounds.CornerMax()
    bbox = [float(getattr(point, axis)()) for point in (low, high) for axis in "XYZ"]
    if not math.isfinite(volume) or not all(map(math.isfinite, bbox)):
        raise ValueError("nonfinite actual geometry metrics")
    result = {"status": "ok", "body_count": len(bodies),
              "solid_count": sum(_solid_count(shape) for shape in shapes),
              "is_valid": all(BRepCheck_Analyzer(shape).IsValid() for shape in shapes),
              "volume": volume, "area": sum(_area(shape) for shape in shapes), "bbox": bbox,
              "build_kernel": getattr(OCP, "__version__", "unknown"),
              "volume_method": "Gauss-Kronrod, epsilon=1e-9, closed shells, BSpline spans",
              "area_method": "Independent geometry copy, C1 continuity spans, adaptive epsilon=1e-10"}
    if reference_step is not None:
        try:
            result.update(_compare_reference(shapes, reference_step))
        except Exception as exc:
            result.update(reference_status="error", reference_error=f"{type(exc).__name__}: {exc}")
    if export_step is not None:
        try:
            result["reference_export_options"] = _export_step(shapes, export_step, export_options)
        except Exception as exc:
            result.update(reference_status="error", reference_error=f"{type(exc).__name__}: {exc}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ftc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--reference-step", type=Path)
    parser.add_argument("--export-step", type=Path)
    parser.add_argument("--export-options", type=json.loads)
    args = parser.parse_args()
    try:
        result = run(args.ftc, args.staging_dir, args.reference_step, args.export_step, args.export_options)
    except BaseException as exc:
        result = {"status": "build_error", "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc(limit=5)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
