#include "scad/ops/geometry/splines.hpp"

#include <cmath>

#include "internal.hpp"
#include "scad/ops/geometry/bspline_args.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr const char* kEdgeOp = "make_spline_redge";

Value number_list(const std::vector<double>& numbers) {
  Value list = Value::array();
  for (const double number : numbers) list.push_back(Value(number));
  return list;
}

Value integer_list(const std::vector<int>& numbers) {
  Value list = Value::array();
  for (const int number : numbers) list.push_back(Value(number));
  return list;
}

Value point_list(const std::vector<Vec3>& points) {
  Value list = Value::array();
  for (const Vec3& p : points) list.push_back(Value(Value::Array{Value(p.x), Value(p.y), Value(p.z)}));
  return list;
}

// What the spline edge was built from, after validation: the values the record keeps.
struct BuiltSpline {
  TopoDS_Edge edge;
  int degree = 0;
  bool periodic = false;
  bspline::Knots knots;
  Value geo;
};

const ErrorSpec& spline_edge_spec() {
  static const ErrorSpec spec{kEdgeOp,
                              "Failed to create a spline edge.",
                              {"The exact B-spline definition is inconsistent.",
                               "Control points, knots, multiplicities, or weights are invalid.",
                               "A sampled-point list was passed directly instead of fitted control points."},
                              {"Pass keyword arguments such as control_points=..., degree=3, knots=..., multiplicities=....",
                               "Use fit_cubic_bspline_control_points(sample_points) for sampled curves, then pass its result fields explicitly.",
                               "Ensure sum(multiplicities) matches the exact B-spline degree/control-count rule."}};
  return spec;
}

int checked_degree(double degree) {
  if (std::isnan(degree) || std::floor(degree) != degree) throw ValueError("degree must be an integer");
  if (degree < 1) throw ValueError("degree must be at least 1");
  if (degree > 25) throw ValueError("degree must be 25 or lower");
  return static_cast<int>(degree);
}

BuiltSpline build_spline(const SplineSpec& spec) {
  return guarded(spline_edge_spec(), [&] {
    BuiltSpline built;
    built.degree = checked_degree(spec.degree);
    built.periodic = spec.periodic;

    const std::vector<Vec3> poles = bspline::control_points(spec.control_points);
    const int count = static_cast<int>(poles.size());
    if (count < built.degree + 1) throw ValueError("control point count must be at least degree + 1");
    built.knots = bspline::normalize_knots(count, built.degree, built.periodic, spec.knots, spec.multiplicities);
    const std::optional<std::vector<double>> weights = bspline::normalize_weights(spec.weights, count);

    const CoordinateSystem& cs = current_cs();
    std::vector<Vec3> placed;
    placed.reserve(poles.size());
    for (const Vec3& pole : poles) placed.push_back(cs.transform_point(pole));

    built.edge = kernel::make_bspline_edge({.control_points = placed,
                                            .degree = built.degree,
                                            .knots = built.knots.unique,
                                            .multiplicities = built.knots.multiplicities,
                                            .weights = weights.value_or(std::vector<double>{}),
                                            .periodic = built.periodic});
    built.geo = Value(Value::Object{{"type", Value("bspline")},
                                    {"degree", Value(built.degree)},
                                    {"control_points", point_list(placed)},
                                    {"knots", number_list(built.knots.unique)},
                                    {"multiplicities", integer_list(built.knots.multiplicities)},
                                    {"weights", weights ? number_list(*weights) : Value()},
                                    {"periodic", Value(built.periodic)}});
    return built;
  });
}

// The record of the edge: validated knots and multiplicities, the poles and weights as given.
OpRecord spline_edge_record(const SplineSpec& spec, const BuiltSpline& built) {
  return OpParams(kEdgeOp, primitive_labels("edge"))
      .coordinates("control_points", spec.control_points)
      .integer("degree", built.degree)
      .numbers("knots", built.knots.unique)
      .integers("multiplicities", built.knots.multiplicities)
      .optional_scalars("weights", spec.weights)
      .boolean("periodic", built.periodic)
      .take();
}

// The record of the unrecorded one-edge wire: the arguments as given.
OpRecord spline_wire_record(const SplineSpec& spec) {
  OpParams params("make_spline_wire", primitive_labels("wire"));
  params.coordinates("control_points", spec.control_points).integer("degree", static_cast<std::int64_t>(spec.degree));
  if (spec.knots) params.scalars("knots", *spec.knots); else params.null("knots");
  if (spec.multiplicities) params.integers("multiplicities", *spec.multiplicities); else params.null("multiplicities");
  return params.optional_scalars("weights", spec.weights).boolean("periodic", spec.periodic).take();
}

constexpr const char* kInterpolatedOp = "make_interpolated_spline_redge";

const ErrorSpec& interpolated_edge_spec() {
  static const ErrorSpec spec{kInterpolatedOp,
                              "Failed to interpolate a B-spline edge through the input points.",
                              {"Too few distinct interpolation points were provided.",
                               "Consecutive points are duplicated or contain invalid coordinates.",
                               "The requested periodic interpolation is geometrically inconsistent."},
                              {"Provide at least two open-curve points or three periodic-curve points.",
                               "Remove consecutive duplicate points; a repeated periodic endpoint is optional.",
                               "Use a smaller positive tolerance when nearby points must remain distinct."}};
  return spec;
}

struct BuiltInterpolation {
  TopoDS_Edge edge;
  double tolerance = 0.0;
  Value geo;
};

BuiltInterpolation build_interpolation(const SplineInterpolation& spec) {
  return guarded(interpolated_edge_spec(), [&] {
    BuiltInterpolation built;
    built.tolerance = evaluate_scalar(spec.tolerance, "tolerance");
    if (!std::isfinite(built.tolerance) || built.tolerance <= 0.0) throw ValueError("tolerance must be a finite positive value");
    const std::vector<Vec3> local = bspline::interpolation_points(spec.points, spec.periodic, built.tolerance);

    const CoordinateSystem& cs = current_cs();
    std::vector<Vec3> placed;
    placed.reserve(local.size());
    for (const Vec3& point : local) placed.push_back(cs.transform_point(point));

    built.edge = kernel::make_interpolated_bspline_edge(placed, spec.periodic, built.tolerance);
    built.geo = Value(Value::Object{{"type", Value("bspline")},
                                    {"construction", Value("interpolated")},
                                    {"interpolation_points", point_list(placed)},
                                    {"periodic", Value(spec.periodic)},
                                    {"tolerance", Value(built.tolerance)}});
    return built;
  });
}

OpRecord interpolation_record(std::string_view op, std::string_view kind, const SplineInterpolation& spec) {
  return OpParams(std::string(op), primitive_labels(kind))
      .coordinates("points", spec.points)
      .boolean("periodic", spec.periodic)
      .scalar("tolerance", spec.tolerance)
      .take();
}

}  // namespace

Edge make_spline_redge(const SplineSpec& spec) {
  return guarded(spline_edge_spec(), [&] {
    BuiltSpline built = build_spline(spec);
    Edge edge(built.edge);
    edge.set_metadata("geo", std::move(built.geo));
    return finalize_primitive_with(std::move(edge), kEdgeOp, [&] { return spline_edge_record(spec, built); });
  });
}

Wire make_spline_rwire(const SplineSpec& spec) {
  static constexpr const char* kOp = "make_spline_rwire";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create a spline wire.",
                               {"The spline edge could not be created.", "The exact B-spline definition is inconsistent.",
                                "The kernel rejected the resulting wire geometry."},
                               {"Validate the B-spline control points, degree, knots, multiplicities, and weights first.",
                                "For sampled curves, call fit_cubic_bspline_control_points(...) and pass the result fields explicitly.",
                                "Retry after inspecting the evaluated spline inputs."}};
  return guarded(kSpec, [&] {
    if (graph_recording()) return make_wire_from_edges_rwire({make_spline_redge(spec)});
    return finalize_primitive_with(Wire(kernel::make_wire_from_edges({build_spline(spec).edge})), "make_spline_wire",
                                   [&] { return spline_wire_record(spec); });
  });
}

Edge make_interpolated_spline_redge(const SplineInterpolation& spec) {
  return guarded(interpolated_edge_spec(), [&] {
    BuiltInterpolation built = build_interpolation(spec);
    Edge edge(built.edge);
    edge.set_metadata("geo", std::move(built.geo));
    return finalize_primitive_with(std::move(edge), kInterpolatedOp,
                                   [&] { return interpolation_record(kInterpolatedOp, "edge", spec); });
  });
}

Wire make_interpolated_spline_rwire(const SplineInterpolation& spec) {
  static constexpr const char* kOp = "make_interpolated_spline_rwire";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create an interpolated spline wire.",
                               {"The interpolated spline edge could not be created.",
                                "The kernel rejected the resulting one-edge wire."},
                               {"Validate the interpolation points and tolerance.",
                                "Use periodic=True for a closed profile and omit a duplicated final point."}};
  return guarded(kSpec, [&] {
    if (graph_recording()) return make_wire_from_edges_rwire({make_interpolated_spline_redge(spec)});
    return finalize_primitive_with(Wire(kernel::make_wire_from_edges({build_interpolation(spec).edge})),
                                   "make_interpolated_spline_wire",
                                   [&] { return interpolation_record("make_interpolated_spline_wire", "wire", spec); });
  });
}

Wire make_periodic_spline_rwire(const std::vector<ScalarPoint>& points, const Scalar& tolerance) {
  return make_interpolated_spline_rwire({.points = points, .periodic = true, .tolerance = tolerance});
}

}  // namespace scad
