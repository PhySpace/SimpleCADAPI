# NURBS editing in a GUI: what the SDK can and cannot do today

Status: research, 2026-11-04, branch `wip/types-surface-sketch` (cut from `feat/gui-modeling`). Nothing here is
implemented; the last section lists the C++ operations a Plasticity-level editor would need.

## Two ways into OpenCASCADE from Python

- **Public SDK operations** (`*_r<kind>` in `simplecadapi`, `simplecadapi.surface`). They are recorded in the graph,
  replay, carry tags and appear in `simplecadapi.catalog`. A GUI or agent can only rely on these.
- **The private OCP-compat layer** `simplecadapi._cpp.occt.*` (`src/cpp/bindings/python/occt/bind_occt_{core,query,algo}.cpp`),
  reached from a shape through `Shape.wrapped` (`bind_topo.cpp`, `bind_common`). It mirrors part of OCP for the internal
  Python layers (inspect, translators). It is not recorded, not replayable and not documented. Edits made through it are
  invisible to the graph and have no way back into topology.

Legend: **public** = a recorded SDK op; **private** = only through `_cpp.occt`; **internal** = used inside the C++ kernel, not
exposed; **absent** = not linked anywhere.

## Capability by capability

| Capability | Status | Evidence |
|---|---|---|
| Read poles / weights / knots / multiplicities / degree of an existing Edge | public (read-only) | `inspect_shape_rbrepinspection` (`src/simplecadapi/inspect/brep/inspect.py`, `_edge_parameters`); native `_bspline_curve_of(edge)` (`bind_sdk_compat.cpp`, `bspline_curve_dict`) |
| Same for a Face | public (read-only) | `inspect.py` `_surface_parameters` (poles, weights, knots, mults of a B-spline surface) |
| Read through OCCT objects | private | `Geom_BSplineCurve` / `Geom_BSplineSurface` / Bezier bound in `bind_occt_query.cpp` (Poles, Weights, Knots, Multiplicities, Degree, UDegree/VDegree); `BRep_Tool.Curve_s/Surface_s/CurveOnSurface_s` in `bind_occt_core.cpp` |
| Write a pole / weight / knot of an existing curve | private only | `bind_occt_query.cpp`: `Geom_BSplineCurve.SetPole/SetWeight/SetKnot(s)/IncreaseMultiplicity`, Bezier `SetPole/SetWeight` |
| Write a pole / weight of an existing surface | private only | `Geom_BSplineSurface.SetPole/SetWeight`, `Geom_BezierSurface.SetPole/SetWeight` (`bind_occt_query.cpp`) |
| Rebuild an Edge/Face after such an edit | absent | no op rebuilds topology from a modified `Geom_*`; the modified handle is shared with the original shape (mutation in place, unrecorded) |
| Degree elevation | private only | `Geom_BSplineCurve.IncreaseDegree`, `Geom_BSplineSurface.IncreaseDegree` (`bind_occt_query.cpp`) |
| Knot insertion / removal | private, curves only | `Geom_BSplineCurve.InsertKnot/RemoveKnot` (`bind_occt_query.cpp`); no `InsertUKnot/RemoveUKnot` for surfaces |
| Fit a surface through a point grid | public | `fit_point_grid_rface` (`src/cpp/src/surface/fitter.cpp`, `GeomAPI_PointsToBSplineSurface`, smoothing weights) |
| Interpolate a curve through points | public | `make_interpolated_spline_redge/rwire`, `make_periodic_spline_rwire` (`src/cpp/src/kernel/curves.cpp`, `GeomAPI_Interpolate`) |
| Approximate a curve (least squares, tolerance) | absent | `GeomAPI_PointsToBSpline` is not linked |
| Refit / simplify an existing curve or face, convert to NURBS | private / absent | `GeomConvert.CurveToBSplineCurve_s/SurfaceToBSplineSurface_s` private (`bind_occt_query.cpp`); `BRepBuilderAPI_NurbsConvert`, `ShapeCustom`, `BSplineRestriction`, `Approx_*` absent |
| G0/G1/G2 boundary conditions when filling | public | `make_surface_patch_rface`, `fill_holes_rshell` with `SurfaceBoundary(edge, continuity="C0"/"G1"/"G2", support=face)` -> `BRepOffsetAPI_MakeFilling` (`fitter.cpp`, `order_of`) |
| Continuity analysis between two faces (G0/G1/G2 deviation along an edge) | absent (one internal probe) | `LocalAnalysis`, `GeomLProp` not linked; dihedral angle along an edge is internal (`src/cpp/src/ops/features/probes.cpp`) |
| Gordon / ruled / loft / Bezier surfaces | public | `make_gordon_surface_rface` (`gordon.cpp`), `make_ruled_surface_rface`, `loft_rshell` / `loft_rsolid`, `make_bezier_surface_rface` (`faces_from_data.cpp`), sweeps (`sweep_rsolid`, `sweep_multisection_rsolid`, ...) |
| Blend surface between two faces (free, not a solid edge) | absent | only `fillet_rsolid` / `chamfer_rsolid` on solid edges (`BRepFilletAPI_*`, `semantic/tracking_blends.cpp`); no `GeomFill_*` / `BRepBlend` |
| Offset a surface | absent | `offset_rsolid` / `shell_rsolid` are solid-only (`ops/features/offsets.cpp`, `MakeThickSolid`); no `Geom_OffsetSurface`, no face offset |
| Extend a surface | absent | no `GeomLib::ExtendSurfByLength`, no `ShapeExtend` |
| Trim a surface by curves | public | `trim_surface_rface(carrier, outer, holes)` (`src/cpp/src/surface/trim.cpp`: projects the wire, checks pcurves with `GeomLib_CheckCurveOnSurface`, `BRepAlgoAPI_Common`) |
| Split a face by a curve | absent (internal splitter) | `BRepAlgoAPI_Splitter` only inside `extrude_until`; no `BRepFeat_SplitShape` |
| Untrim / read the trimming loops in UV | internal | pcurves read in `trim.cpp` via `BRep_Tool::CurveOnSurface`; no op returns them |
| Curve on surface (edge from a 2D curve on a face) | absent | `BRepBuilderAPI_MakeEdge(Geom2d_Curve, Surface)` not bound/used (MakeEdge takes 3D curves only, `bind_occt_algo.cpp`) |
| Project a point onto a surface | internal / private | `GeomAPI_ProjectPointOnSurf` in `trim.cpp`, `ShapeAnalysis_Surface` in `probes.cpp`; private binding in `bind_occt_query.cpp` |
| Project a curve onto a surface | absent | `BRepProj_Projection` not linked; `project_rsketch` only projects onto a sketch plane (`src/cpp/src/sketch/project.cpp`) |
| Isocurves (U/V iso lines) | private | `Geom_Surface.UIso/VIso` (`bind_occt_query.cpp`); used inside the guided-loft recipe (`bind_sdk_compat.cpp`); no op |
| Evaluate a curve / surface (point, derivatives, curvature) | private (sampling public) | `Edge.sample(count)` public (`bind_ops_geometry.cpp`); `D0..DN`, `BRepLProp_SLProps` curvatures private; no curve curvature (`CLProps`), no curvature comb |
| Sketch B-splines with poles / knots / weights | public | `add_bspline_rsketch(..., control_points, degree, knots, multiplicities, weights, periodic)` (`bind_sketch.cpp`); 3D `make_spline_redge/rwire` (`bind_ops_geometry.cpp`) |
| Editor hooks for control-point editing | absent | `src/simplecadapi/editor` only maps `bspline_curve/surface` to the BSPLINE selection filter (`editor/selection.py`) |

OCCT classes already linked: Geom_BSplineCurve/Surface, Geom_Bezier*, GeomAPI_Interpolate, GeomAPI_PointsToBSplineSurface,
BRepOffsetAPI_MakeFilling, ThruSections, MakePipeShell, MakeThickSolid, MakeOffset (wires), BRepFill, BRepFilletAPI,
GeomConvert, GeomAPI_ProjectPointOnSurf, ShapeAnalysis_Surface/FreeBounds, GeomLib_CheckCurveOnSurface, BRepAlgoAPI_Common/Splitter,
BRepLProp_SLProps, Geom2d_*, BRepExtrema.

Not linked: GeomPlate, GeomFill, LocalAnalysis, GeomLProp, Geom_OffsetSurface, GeomLib::ExtendSurfByLength, ShapeExtend,
ShapeCustom, BRepBuilderAPI_NurbsConvert, BRepFeat_SplitShape, BRepProj_Projection, GeomAPI_PointsToBSpline, Approx_*.

## What this means for a GUI

The SDK can *build* every common freeform surface from data a GUI collects (control nets, curve networks, boundary
patches with G1/G2 supports, trims), and it can *read* the NURBS data of a result. It cannot *edit* an existing curve
or surface as a recorded operation: every edit a Plasticity-style control-point drag implies (move pole, set weight,
insert knot, elevate degree) exists only as unrecorded mutation through the private OCCT layer, and nothing rebuilds the
Edge/Face from the modified geometry. The editor must therefore keep the control net itself and re-run a constructor op
(`make_spline_redge`, `make_bezier_surface_rface`) on every drag, which loses the identity and tags of downstream topology
and has no answer for imported or derived (fillet, Gordon, filling) surfaces.

## Operations that would be needed (C++ kernel ops, recorded, catalog-typed)

Read:
1. `inspect_curve_rnurbs(edge)` / `inspect_surface_rnurbs(face)` - degree, poles (`Sequence[Point3]` / grid), weights,
   knots, multiplicities, periodic/rational flags, parameter range; converts non-B-spline geometry on request
   (`GeomConvert`). Today's data sits in `inspect_shape_rbrepinspection`; it needs to be a first-class typed value.
2. `evaluate_curve_rframe(edge, t)` / `evaluate_surface_rframe(face, u, v)` - point, derivatives, normal, curvatures
   (`GeomLProp_CLProps/SLProps`), for curvature combs and zebra-like checks.
3. `measure_continuity_rcontinuity(face_a, face_b, edge, samples)` - G0 gap, G1 angle, G2 curvature deviation
   (`LocalAnalysis_SurfaceContinuity`).

Edit (each returns a new Edge/Face, recorded, lineage preserved for tags):
4. `edit_curve_poles_redge(edge, poles=..., weights=...)` and `edit_surface_poles_rface(face, poles=..., weights=...)`
   - replace some or all poles/weights, keep the trim (re-project the face's trim loops).
5. `insert_knot_redge` / `insert_knot_rface(face, u=|v=, multiplicity)`, `remove_knot_*` (tolerance-checked).
6. `elevate_degree_redge` / `elevate_degree_rface(face, u_degree, v_degree)`.
7. `rebuild_curve_redge(edge, degree, pole_count | tolerance)` / `rebuild_surface_rface(face, u_count, v_count, degree)`
   (`GeomAPI_PointsToBSpline(Surface)`, `Approx_*`) and `convert_to_nurbs_rshape` (`BRepBuilderAPI_NurbsConvert`).

Build:
8. `blend_surface_rface(edge_a, face_a, edge_b, face_b, continuity="G1"|"G2")` (`GeomFill` / `GeomPlate`).
9. `offset_surface_rface(face, distance)` (`BRepOffsetAPI_MakeOffsetShape` on a face, `Geom_OffsetSurface`) and
   `extend_surface_rface(face, edge, length, continuity)` (`GeomLib::ExtendSurfByLength`).
10. `split_face_rfacelist(face, tools)` (`BRepFeat_SplitShape` / `BRepAlgoAPI_Splitter`), `untrim_surface_rface(face)`.
11. `make_curve_on_surface_redge(face, uv_points | Geom2d spec)` and `project_curve_onto_face_redge(edge, face,
    direction=None)` (`BRepProj_Projection`, `BRepAlgo_NormalProjection`).
12. `make_isocurve_redge(face, u=|v=)` (`UIso/VIso` + trim to the face).

Most important gaps, in order: (a) recorded edits of an existing curve/surface (4-6) - without them control-point
editing is a rebuild-from-scratch hack; (b) continuity measurement and blend surfaces (3, 8) - the core of class-A style
surfacing; (c) offset/extend/split of faces (9, 10) - routine surface workflow steps that have no op at all.
