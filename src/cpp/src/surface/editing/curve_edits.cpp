// set_curve_poles_redge, move_curve_poles_redge, set_curve_weights_redge, insert_curve_knot_redge,
// elevate_curve_degree_redge: edits of an edge's B-spline that keep its parametrisation.
#include <cmath>
#include <string>

#include "access.hpp"
#include "finish.hpp"
#include "scad/surface/editing.hpp"

namespace scad {

using namespace surface::editing;

namespace {

ErrorSpec curve_spec(const char* op, const char* what) {
  return ErrorSpec{op,
                   what,
                   {"The edge does not carry a B-spline or Bezier curve.", "An argument does not fit the curve."},
                   {"Convert analytic edges (lines, circles) with convert_to_bspline_redge first.",
                    "Read the curve with inspect_curve_rcurvedata: pole count, degree, parameter range."}};
}

Value points_value(const std::vector<Vec3>& points) {
  Value::Array out;
  for (const Vec3& p : points)
    out.push_back(point_value(p));
  return Value(std::move(out));
}

std::string count_text(int count) {
  return std::to_string(count);
}

// The multiplicity `parameter` already has as a knot (0 when it is none).
int existing_multiplicity(const Handle(Geom_BSplineCurve) & curve, double parameter) {
  for (int i = 1; i <= curve->NbKnots(); ++i)
    if (std::abs(curve->Knot(i) - parameter) <= 1e-9 * std::max(1.0, std::abs(parameter)))
      return curve->Multiplicity(i);
  return 0;
}

}  // namespace

Edge set_curve_poles_redge(const Edge& edge, const std::vector<Vec3>& poles, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = curve_spec("set_curve_poles_redge", "Failed to set the poles of the curve.");
  return edit_scope(kSpec, [&] {
    EditableCurve c = editable_curve(edge);
    if (static_cast<int>(poles.size()) != c.curve->NbPoles())
      throw ValueError("poles must hold exactly " + count_text(c.curve->NbPoles()) +
                       " points (the curve's pole count), got " + count_text(static_cast<int>(poles.size())));
    for (std::size_t i = 0; i < poles.size(); ++i) {
      require_finite(poles[i], "poles");
      c.curve->SetPole(static_cast<int>(i) + 1, rep_point(poles[i], c.location));
    }
    Value params = Value::object();
    params.set("poles", points_value(poles));
    return finish_edge(edge, "set_curve_poles_redge", std::move(params), tag_prefix, c.curve, c.location);
  });
}

Edge move_curve_poles_redge(const Edge& edge, const std::map<int, Vec3>& moves, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = curve_spec("move_curve_poles_redge", "Failed to move poles of the curve.");
  return edit_scope(kSpec, [&] {
    EditableCurve c = editable_curve(edge);
    if (moves.empty())
      throw ValueError("moves must name at least one pole");
    Value::Array recorded;
    for (const auto& [index, position] : moves) {
      if (index < 0 || index >= c.curve->NbPoles())
        throw ValueError("pole index " + std::to_string(index) + " is out of range: the curve has " +
                         count_text(c.curve->NbPoles()) + " poles (0-based indices)");
      require_finite(position, "moves");
      c.curve->SetPole(index + 1, rep_point(position, c.location));
      recorded.emplace_back(Value::Array{index, point_value(position)});
    }
    Value params = Value::object();
    params.set("moves", Value(std::move(recorded)));
    return finish_edge(edge, "move_curve_poles_redge", std::move(params), tag_prefix, c.curve, c.location);
  });
}

Edge set_curve_weights_redge(const Edge& edge, const std::vector<double>& weights, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = curve_spec("set_curve_weights_redge", "Failed to set the weights of the curve.");
  return edit_scope(kSpec, [&] {
    EditableCurve c = editable_curve(edge);
    if (static_cast<int>(weights.size()) != c.curve->NbPoles())
      throw ValueError("weights must hold exactly " + count_text(c.curve->NbPoles()) + " values (one per pole), got " +
                       count_text(static_cast<int>(weights.size())));
    Value::Array recorded;
    for (std::size_t i = 0; i < weights.size(); ++i) {
      if (!std::isfinite(weights[i]) || weights[i] <= 0.0)
        throw ValueError("weights must be positive finite values");
      c.curve->SetWeight(static_cast<int>(i) + 1, weights[i]);
      recorded.emplace_back(weights[i]);
    }
    Value params = Value::object();
    params.set("weights", Value(std::move(recorded)));
    return finish_edge(edge, "set_curve_weights_redge", std::move(params), tag_prefix, c.curve, c.location);
  });
}

Edge insert_curve_knot_redge(const Edge& edge, double parameter, int multiplicity, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = curve_spec("insert_curve_knot_redge", "Failed to insert a knot into the curve.");
  return edit_scope(kSpec, [&] {
    EditableCurve c = editable_curve(edge);
    if (!std::isfinite(parameter) || parameter <= c.first || parameter >= c.last)
      throw ValueError("parameter must lie strictly inside the edge's parameter range [" + std::to_string(c.first) +
                       ", " + std::to_string(c.last) + "]");
    const int degree = c.curve->Degree();
    if (multiplicity < 1 || multiplicity + existing_multiplicity(c.curve, parameter) > degree)
      throw ValueError("multiplicity must be at least 1 and the knot's total multiplicity at most the degree (" +
                       count_text(degree) + ")");
    c.curve->InsertKnot(parameter, multiplicity, 1e-9, Standard_True);
    Value params = Value::object();
    params.set("parameter", parameter);
    params.set("multiplicity", multiplicity);
    return finish_edge(edge, "insert_curve_knot_redge", std::move(params), tag_prefix, c.curve, c.location);
  });
}

Edge elevate_curve_degree_redge(const Edge& edge, int degree, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = curve_spec("elevate_curve_degree_redge", "Failed to elevate the degree of the curve.");
  return edit_scope(kSpec, [&] {
    EditableCurve c = editable_curve(edge);
    if (degree <= c.curve->Degree() || degree > Geom_BSplineCurve::MaxDegree())
      throw ValueError("degree must be higher than the curve's degree (" + count_text(c.curve->Degree()) +
                       ") and at most " + count_text(Geom_BSplineCurve::MaxDegree()));
    c.curve->IncreaseDegree(degree);
    Value params = Value::object();
    params.set("degree", degree);
    return finish_edge(edge, "elevate_curve_degree_redge", std::move(params), tag_prefix, c.curve, c.location);
  });
}

}  // namespace scad
