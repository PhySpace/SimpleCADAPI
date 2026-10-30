// trim_surface_rface: project closed 3D wires onto a carrier face and intersect.
//
// Port of trim_surface_face and its helpers in kernel/ocp_surfaces.py.  The checks are
// ordered and worded like the Python ones; their messages are what callers (and tests)
// match on.
#include <algorithm>
#include <cmath>
#include <optional>

#include <Adaptor3d_CurveOnSurface.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepCheck_Wire.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <Geom2dAdaptor_Curve.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomLib_CheckCurveOnSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <ShapeFix_Edge.hxx>
#include <ShapeFix_Wire.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>

#include "finalize.hpp"
#include "internal.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/surface/operators.hpp"

namespace scad {

using namespace surface::detail;

namespace {

// ---- periodic parameter windows -------------------------------------------------------------
std::vector<double> unwrap_periodic(const std::vector<double>& values, double period) {
  std::vector<double> result{values.front()};
  for (std::size_t i = 1; i < values.size(); ++i)
    result.push_back(values[i] + std::nearbyint((result.back() - values[i]) / period) * period);
  return result;
}

bool fits_parameter_bounds(const std::vector<double>& values, double lower, double upper, double tolerance,
                           std::optional<double> period) {
  if (!period)
    return std::all_of(values.begin(), values.end(),
                       [&](double v) { return lower - tolerance <= v && v <= upper + tolerance; });
  const std::vector<double> checked = unwrap_periodic(values, *period);
  const auto [lowest, highest] = std::minmax_element(checked.begin(), checked.end());
  if (*highest - *lowest > upper - lower + 2.0 * tolerance)
    return false;
  const double minimum_shift = std::ceil((lower - tolerance - *lowest) / *period);
  const double maximum_shift = std::floor((upper + tolerance - *highest) / *period);
  return minimum_shift <= maximum_shift;
}

// ---- sampling -----------------------------------------------------------------------------------
// By arc length, densely enough to preserve periodic winding.
std::vector<double> curve_sample_parameters(const BRepAdaptor_Curve& adaptor, const Handle(Geom_Surface) & surface) {
  int sample_count = 65;
  const GeomAbs_CurveType type = adaptor.GetType();
  if (type == GeomAbs_BSplineCurve || type == GeomAbs_BezierCurve)
    sample_count = std::max(sample_count, 8 * adaptor.NbPoles() + 1);
  if (const Handle(Geom_CylindricalSurface) cylinder = Handle(Geom_CylindricalSurface)::DownCast(surface)) {
    const double length = GCPnts_AbscissaPoint::Length(adaptor);
    const double quarter_period = cylinder->Radius() * kPi / 2.0;
    if (std::isfinite(length) && quarter_period > 0.0)
      sample_count = std::max(sample_count, static_cast<int>(std::ceil(length / quarter_period)) + 1);
  }

  const GCPnts_UniformAbscissa sampler(adaptor, sample_count);
  std::vector<double> parameters;
  if (sampler.IsDone() && sampler.NbPoints() >= sample_count) {
    for (int i = 1; i <= sampler.NbPoints(); ++i)
      parameters.push_back(sampler.Parameter(i));
    return parameters;
  }
  const double first = adaptor.FirstParameter();
  const double last = adaptor.LastParameter();
  for (int i = 0; i < sample_count; ++i)
    parameters.push_back(first + (last - first) * i / (sample_count - 1));
  return parameters;
}

// ---- orientation --------------------------------------------------------------------------------
// Signed area of the wire's loop in the parameter space of `support`.
double wire_uv_area(const TopoDS_Wire& wire, const TopoDS_Face& support) {
  std::vector<gp_Pnt2d> points;
  for (BRepTools_WireExplorer explorer(wire, support); explorer.More(); explorer.Next()) {
    const TopoDS_Edge edge = explorer.Current();
    double first = 0.0, last = 0.0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, support, first, last);
    if (pcurve.IsNull())
      throw ValueError("trim wire edge has no pcurve on the carrier");
    std::vector<double> parameters;
    for (int i = 0; i < 8; ++i)
      parameters.push_back(first + (last - first) * i / 7.0);
    if (edge.Orientation() == TopAbs_REVERSED)
      std::reverse(parameters.begin(), parameters.end());
    for (std::size_t i = 0; i + 1 < parameters.size(); ++i)
      points.push_back(pcurve->Value(parameters[i]));
  }
  if (points.size() < 3)
    throw ValueError("trim wire has fewer than three UV samples");
  double twice_area = 0.0;
  for (std::size_t i = 0; i < points.size(); ++i) {
    const gp_Pnt2d& a = points[i];
    const gp_Pnt2d& b = points[(i + 1) % points.size()];
    twice_area += a.X() * b.Y() - b.X() * a.Y();
  }
  return 0.5 * twice_area;
}

// ---- validation -------------------------------------------------------------------------------------
void validate_closed_trim_wire(const TopoDS_Wire& wire, const std::string& description) {
  if (BRepCheck_Wire(wire).Closed() != BRepCheck_NoError)
    throw ValueError(description + " trim wire must be closed");
}

void validate_trim_wire_domain(const TopoDS_Wire& wire, const TopoDS_Face& carrier, double tolerance) {
  const Handle(Geom_Surface) surface = BRep_Tool::Surface(carrier);
  double u_min = 0, u_max = 0, v_min = 0, v_max = 0;
  BRepTools::UVBounds(carrier, u_min, u_max, v_min, v_max);

  std::vector<double> u_values, v_values;
  int edge_index = 0;
  for (BRepTools_WireExplorer explorer(wire); explorer.More(); explorer.Next(), ++edge_index) {
    const TopoDS_Edge edge = explorer.Current();
    const BRepAdaptor_Curve adaptor(edge);
    std::vector<double> parameters = curve_sample_parameters(adaptor, surface);
    if (edge.Orientation() == TopAbs_REVERSED)
      std::reverse(parameters.begin(), parameters.end());
    for (std::size_t sample = 0; sample < parameters.size(); ++sample) {
      if (edge_index != 0 && sample == 0)
        continue;
      const GeomAPI_ProjectPointOnSurf projection(adaptor.Value(parameters[sample]), surface);
      if (projection.NbPoints() == 0)
        throw ValueError("trim edge " + std::to_string(edge_index) + " could not be projected onto the carrier");
      double u = 0.0, v = 0.0;
      projection.LowerDistanceParameters(u, v);
      u_values.push_back(u);
      v_values.push_back(v);
    }
  }
  if (edge_index < 1)
    throw ValueError("trim wire contains no edges");

  const std::optional<double> u_period = surface->IsUPeriodic() ? std::optional(surface->UPeriod()) : std::nullopt;
  const std::optional<double> v_period = surface->IsVPeriodic() ? std::optional(surface->VPeriod()) : std::nullopt;
  double u_tolerance = tolerance;
  if (const Handle(Geom_CylindricalSurface) cylinder = Handle(Geom_CylindricalSurface)::DownCast(surface))
    u_tolerance = tolerance / cylinder->Radius();
  const bool u_outside = u_period && !fits_parameter_bounds(u_values, u_min, u_max, u_tolerance, u_period);
  const bool v_outside = v_period && !fits_parameter_bounds(v_values, v_min, v_max, tolerance, v_period);
  if (u_outside || v_outside)
    throw ValueError("trim wire lies outside the bounded carrier parameter domain");
}

// ---- projection ---------------------------------------------------------------------------------------
TopoDS_Wire project_trim_wire(const TopoDS_Wire& wire, const TopoDS_Face& support, double tolerance) {
  BRepBuilderAPI_Copy copied(wire, true, false);
  if (!copied.IsDone() || copied.Shape().IsNull())
    throw ValueError("OCP could not copy the trim wire");
  TopoDS_Wire result = TopoDS::Wire(copied.Shape());

  ShapeFix_Edge edge_fix;
  int edge_count = 0;
  for (BRepTools_WireExplorer explorer(result); explorer.More(); explorer.Next(), ++edge_count) {
    const TopoDS_Edge edge = explorer.Current();
    const std::string index = std::to_string(edge_count);
    edge_fix.FixAddPCurve(edge, support, false, tolerance);
    double first = 0.0, last = 0.0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, support, first, last);
    if (pcurve.IsNull())
      throw ValueError("trim edge " + index + " could not be projected");

    GeomLib_CheckCurveOnSurface check(new BRepAdaptor_Curve(edge), tolerance);
    check.Perform(
        new Adaptor3d_CurveOnSurface(new Geom2dAdaptor_Curve(pcurve, first, last), new BRepAdaptor_Surface(support)));
    if (!check.IsDone() || check.ErrorStatus() != 0)
      throw ValueError("trim edge " + index + " could not be validated against the carrier");
    if (check.MaxDistance() > tolerance)
      throw ValueError("trim edge " + index + " deviates from the carrier beyond tolerance");
    edge_fix.FixSameParameter(edge, support, tolerance);
  }
  if (edge_count < 1)
    throw ValueError("trim wire contains no edges");

  ShapeFix_Wire wire_fix(result, support, tolerance);
  wire_fix.Perform();
  result = wire_fix.Wire();
  if (result.IsNull() || !BRepCheck_Analyzer(result).IsValid())
    throw ValueError("projected trim wire is invalid");
  BRepCheck_Wire wire_check(result);
  if (wire_check.Closed() != BRepCheck_NoError)
    throw ValueError("projected trim wire must be closed");
  TopoDS_Edge first_intersection, second_intersection;
  if (wire_check.SelfIntersect(support, first_intersection, second_intersection) != BRepCheck_NoError)
    throw ValueError("projected trim wire must be simple and non-self-intersecting");
  return result;
}

TopoDS_Face single_trimmed_face(const TopoDS_Shape& shape, const std::string& description) {
  if (shape.ShapeType() == TopAbs_FACE)
    return TopoDS::Face(shape);
  const std::vector<TopoDS_Face> faces = kernel::faces_of(shape);
  if (faces.empty())
    throw ValueError(description + " must produce exactly one connected Face; intersection is empty");
  if (faces.size() != 1)
    throw ValueError(description + " must produce exactly one connected Face; intersection produced " +
                     std::to_string(faces.size()) + " disconnected Faces");
  return faces.front();
}

// occt_guard: the caller trim_surface_rface runs this inside operator_scope (which is guarded + occt_guard).
TopoDS_Face trim_surface_face(const TopoDS_Face& carrier, const TopoDS_Wire& outer,
                              const std::vector<TopoDS_Wire>& holes, double tolerance) {
  const Handle(Geom_Surface) surface = BRep_Tool::Surface(carrier);
  if ((surface->IsUPeriodic() || surface->IsVPeriodic()) && !holes.empty())
    throw ValueError("periodic carrier trimming with holes is not supported");
  validate_closed_trim_wire(outer, "outer");
  for (std::size_t i = 0; i < holes.size(); ++i)
    validate_closed_trim_wire(holes[i], "hole " + std::to_string(i));
  validate_trim_wire_domain(outer, carrier, tolerance);
  for (const TopoDS_Wire& wire : holes)
    validate_trim_wire_domain(wire, carrier, tolerance);

  BRepBuilderAPI_MakeFace support_builder;
  support_builder.Init(surface, false, tolerance);
  const TopoDS_Face support = support_builder.Face();
  TopoDS_Wire outer_wire = project_trim_wire(outer, support, tolerance);
  std::vector<TopoDS_Wire> hole_wires;
  for (const TopoDS_Wire& wire : holes)
    hole_wires.push_back(project_trim_wire(wire, support, tolerance));

  // The requested loop must run the way the carrier's own outer loop does.
  const double carrier_area = wire_uv_area(BRepTools::OuterWire(carrier), carrier);
  double outer_area = wire_uv_area(outer_wire, support);
  if (carrier_area * outer_area < 0.0) {
    outer_wire = TopoDS::Wire(outer_wire.Reversed());
    outer_area = -outer_area;
  }

  BRepBuilderAPI_MakeFace face_builder(surface, outer_wire, true);
  for (const TopoDS_Wire& wire : hole_wires) {
    const double area = wire_uv_area(wire, support);
    face_builder.Add(outer_area * area > 0.0 ? TopoDS::Wire(wire.Reversed()) : wire);
  }
  face_builder.Build();
  if (!face_builder.IsDone() || face_builder.Face().IsNull())
    throw ValueError("OCP could not build the trimmed surface face");
  const TopoDS_Face requested_face = face_builder.Face();

  TopTools_ListOfShape arguments, tools;
  arguments.Append(carrier);
  tools.Append(requested_face);
  BRepAlgoAPI_Common common;
  common.SetArguments(arguments);
  common.SetTools(tools);
  common.SetRunParallel(true);
  common.SetUseOBB(true);
  common.SetNonDestructive(true);
  common.Build();
  if (!common.IsDone())
    throw ValueError("OCP could not intersect the trim with the bounded carrier");
  if (common.Shape().IsNull())
    throw ValueError("trimmed carrier intersection must produce exactly one connected Face; intersection is empty");
  const TopoDS_Face face = single_trimmed_face(common.Shape(), "trimmed carrier intersection");
  if (!BRepCheck_Analyzer(face).IsValid())
    throw ValueError("trimmed surface face is invalid");
  return face;
}

}  // namespace

Face trim_surface_rface(const Face& carrier, const Wire& outer, const TrimSurfaceOptions& options) {
  static const ErrorSpec kSpec{
      "trim_surface_rface",
      "Failed to trim the carrier surface face.",
      {"A trim wire is open, invalid, or does not lie on the carrier.", "A periodic trim crosses the carrier seam.",
       "A hole intersects the outer boundary or another hole.",
       "The bounded intersection is empty or has multiple connected regions."},
      {"Pass one closed, simple outer Wire and optional closed, simple hole Wires.",
       "Keep every trim curve on the carrier within tolerance and inside one periodic seam.",
       "Choose boundaries whose carrier intersection is exactly one connected Face."}};
  return operator_scope(kSpec, [&] {
    const double tolerance = require_positive_finite(options.tolerance, "tolerance");
    std::vector<TopoDS_Wire> holes;
    for (const Wire& hole : options.holes)
      holes.push_back(TopoDS::Wire(hole.wrapped()));

    const TopoDS_Face trimmed =
        trim_surface_face(TopoDS::Face(carrier.wrapped()), TopoDS::Wire(outer.wrapped()), holes, tolerance);

    Value params = Value::object();
    params.set("hole_count", static_cast<std::int64_t>(holes.size()));
    params.set("tolerance", tolerance);
    params.set("tag_prefix", to_value(options.tag_prefix));
    FaceOutput output{.record = {.op = "trim_surface_rface", .params = std::move(params)},
                      .tag_prefix = options.tag_prefix};
    output.record.inputs.push_back({carrier, "carrier"});
    output.record.inputs.push_back({outer, "outer"});
    output.fragment_sources = {carrier, outer};
    for (const Wire& hole : options.holes) {
      output.record.inputs.push_back({hole, "hole"});
      output.fragment_sources.push_back(hole);
    }
    return finalize_surface_output(Face(trimmed), std::move(output));
  });
}

}  // namespace scad
