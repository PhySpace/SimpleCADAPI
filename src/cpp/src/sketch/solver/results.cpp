#include "results.hpp"

#include <algorithm>
#include <cmath>

#include "scad/core/error.hpp"
#include "scad/core/vec.hpp"

namespace scad::sketch_solver {

namespace {

constexpr double kTwoPi = 2.0 * kPi;

Value point_value(const SketchPoint2& p) {
  return Value(Value::Array{Value(p.first), Value(p.second)});
}

double distance(const SketchPoint2& a, const SketchPoint2& b) {
  return std::hypot(a.first - b.first, a.second - b.second);
}

double positive_mod(double value, double modulus) {
  return value - modulus * std::floor(value / modulus);
}

double sweep_of(const SketchPoint2& center, const SketchPoint2& start, const SketchPoint2& end) {
  const double start_angle = std::atan2(start.second - center.second, start.first - center.first);
  const double end_angle = std::atan2(end.second - center.second, end.first - center.first);
  return positive_mod(end_angle - start_angle, kTwoPi);
}

struct Reader {
  const Model& model;
  const std::vector<double>& x;

  double value(int id) const {
    const Param& p = model.system.params[id];
    return p.unknown >= 0 ? x[static_cast<std::size_t>(p.unknown)] : p.value;
  }
  SketchPoint2 point(const Pt& p) const { return {value(p.x), value(p.y)}; }
};

// Cox-de Boor evaluation of a (rational) B-spline at `parameter`, clamped to the
// valid knot range exactly like the Python adapter (which samples [0, 1]).
SketchPoint2 evaluate_bspline(const std::vector<SketchPoint2>& poles, int degree,
                              const std::vector<double>& unique_knots, const std::vector<int>& multiplicities,
                              double parameter, const std::optional<std::vector<double>>& weights) {
  std::vector<double> knots;
  for (std::size_t i = 0; i < unique_knots.size(); ++i) {
    for (int k = 0; k < multiplicities[i]; ++k)
      knots.push_back(unique_knots[i]);
  }
  const std::size_t d = static_cast<std::size_t>(degree);
  const double u = std::min(std::max(parameter, knots[d]), knots[knots.size() - d - 1]);
  if (u >= knots[knots.size() - d - 1])
    return poles.back();

  std::vector<double> basis(knots.size() - 1, 0.0);
  for (std::size_t i = 0; i + 1 < knots.size(); ++i)
    basis[i] = (knots[i] <= u && u < knots[i + 1]) ? 1.0 : 0.0;
  for (std::size_t current = 1; current <= d; ++current) {
    std::vector<double> next(basis.size() - 1, 0.0);
    for (std::size_t i = 0; i < next.size(); ++i) {
      const double left_den = knots[i + current] - knots[i];
      const double right_den = knots[i + current + 1] - knots[i + 1];
      const double left = left_den != 0.0 ? (u - knots[i]) / left_den * basis[i] : 0.0;
      const double right = right_den != 0.0 ? (knots[i + current + 1] - u) / right_den * basis[i + 1] : 0.0;
      next[i] = left + right;
    }
    basis = std::move(next);
  }
  double denominator = 0.0;
  double px = 0.0;
  double py = 0.0;
  for (std::size_t i = 0; i < poles.size(); ++i) {
    const double w = weights ? (*weights)[i] : 1.0;
    const double weighted = basis[i] * w;
    denominator += weighted;
    px += weighted * poles[i].first;
    py += weighted * poles[i].second;
  }
  if (std::abs(denominator) <= 1e-18)
    throw ValueError("B-spline evaluation produced a zero rational denominator");
  return {px / denominator, py / denominator};
}

double bspline_length(const SolvedGeometry& solved, const SketchEntity& entity) {
  const SketchBSpline spline = entity.bspline();
  std::vector<SketchPoint2> poles;
  for (std::size_t i = 0; i < spline.poles.size(); ++i) {
    poles.push_back(solved.points.at("bspline:" + entity.id + ":pole:" + std::to_string(i)));
  }
  constexpr int kSamples = 64;
  double length = 0.0;
  SketchPoint2 previous = poles.front();
  for (int step = 1; step <= kSamples; ++step) {
    const SketchPoint2 current = evaluate_bspline(poles, spline.degree, spline.knots, spline.multiplicities,
                                                  static_cast<double>(step) / kSamples, spline.weights);
    length += distance(previous, current);
    previous = current;
  }
  return length;
}

}  // namespace

SolvedGeometry assemble_solution(const Model& model, const std::vector<double>& x) {
  const Reader read{model, x};
  const Sketch& sketch = model.sketch;
  SolvedGeometry out;

  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind == kPointKind)
      out.points.set(id, read.point(model.points.at(id)));
  }
  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind != kBSplineKind)
      continue;
    const SplineModel& spline = model.splines.at(id);
    for (std::size_t i = 0; i < spline.poles.size(); ++i) {
      out.points.set("bspline:" + id + ":pole:" + std::to_string(i), read.point(spline.poles[i]));
    }
  }

  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind == kCircleKind)
      out.scalars.set("circle:" + id + ":radius", read.value(model.radius_params.at(id)));
  }
  for (const auto& [id, entity] : sketch.entities()) {
    if (entity.kind != kArcKind)
      continue;
    const double radius = distance(out.points.at(entity.point_id("center")), out.points.at(entity.point_id("start")));
    out.scalars.set("arc:" + id + ":radius", radius);
    out.scalars.set("arc:" + id + ":diameter", 2.0 * radius);
  }

  for (const auto& [id, entity] : sketch.entities()) {
    Value solved = Value::object();
    solved.set("kind", entity.kind);
    if (entity.kind == kPointKind) {
      solved.set("point", point_value(out.points.at(id)));
    } else if (entity.kind == kLineKind) {
      const SketchPoint2 start = out.points.at(entity.point_id("start"));
      const SketchPoint2 end = out.points.at(entity.point_id("end"));
      solved.set("start", point_value(start));
      solved.set("end", point_value(end));
      solved.set("length", distance(start, end));
    } else if (entity.kind == kCircleKind) {
      const double radius = out.scalars.at("circle:" + id + ":radius");
      solved.set("center", point_value(out.points.at(entity.point_id("center"))));
      solved.set("radius", radius);
      solved.set("diameter", 2.0 * radius);
    } else if (entity.kind == kArcKind) {
      const SketchPoint2 center = out.points.at(entity.point_id("center"));
      const SketchPoint2 start = out.points.at(entity.point_id("start"));
      const SketchPoint2 end = out.points.at(entity.point_id("end"));
      const double radius = out.scalars.at("arc:" + id + ":radius");
      const double sweep = sweep_of(center, start, end);
      solved.set("center", point_value(center));
      solved.set("start", point_value(start));
      solved.set("end", point_value(end));
      solved.set("radius", radius);
      solved.set("sweep", sweep);
      solved.set("length", radius * sweep);
    } else if (entity.kind == kEllipseKind) {
      const SketchPoint2 center = out.points.at(entity.point_id("center"));
      const SketchPoint2 major = out.points.at(entity.point_id("major"));
      const SketchPoint2 minor = out.points.at(entity.point_id("minor"));
      solved.set("center", point_value(center));
      solved.set("major_point", point_value(major));
      solved.set("minor_point", point_value(minor));
      solved.set("major_radius", distance(center, major));
      solved.set("minor_radius", distance(center, minor));
      solved.set("angle", std::atan2(major.second - center.second, major.first - center.first) * 180.0 / kPi);
    } else if (entity.kind == kBSplineKind) {
      const SplineModel& spline = model.splines.at(id);
      Value::Array poles;
      for (std::size_t i = 0; i < spline.poles.size(); ++i) {
        poles.push_back(point_value(out.points.at("bspline:" + id + ":pole:" + std::to_string(i))));
      }
      solved.set("degree", spline.definition.degree);
      solved.set("control_points", Value(std::move(poles)));
      solved.set("knots", *entity.data.find("knots"));
      solved.set("multiplicities", *entity.data.find("multiplicities"));
      solved.set("weights", *entity.data.find("weights"));
      solved.set("periodic", spline.definition.periodic);
      solved.set("segment_count", static_cast<int>(spline.segments.size()));
      solved.set("solver_representation", spline.cubic_bezier ? "cubic_bezier" : "fixed_shape");
    } else {
      continue;
    }
    out.entities.set(id, std::move(solved));
  }
  return out;
}

void add_measurements(const Model& model, SolvedGeometry& solved) {
  const Sketch& sketch = model.sketch;
  const auto point_of = [&](const SketchRef& ref) { return solved.points.at(sketch.resolve_point_id(ref)); };
  for (const SketchConstraint* constraint : model.measurements) {
    const std::string key = "constraint:" + constraint->id + ":value";
    const std::string& kind = constraint->kind;
    const auto target = [&](std::size_t i) -> const SketchRef& { return model.target(*constraint, i); };
    double value = 0.0;
    if (kind == "distance") {
      value = distance(point_of(target(0)), point_of(target(1)));
    } else if (kind == "distance_x") {
      value = point_of(target(1)).first - point_of(target(0)).first;
    } else if (kind == "distance_y") {
      value = point_of(target(1)).second - point_of(target(0)).second;
    } else if (kind == "length") {
      const SketchEntity& entity = model.entity(target(0));
      if (entity.kind == kBSplineKind) {
        value = bspline_length(solved, entity);
      } else if (entity.kind == kArcKind) {
        const SketchPoint2 center = solved.points.at(entity.point_id("center"));
        const SketchPoint2 start = solved.points.at(entity.point_id("start"));
        value = distance(center, start) * sweep_of(center, start, solved.points.at(entity.point_id("end")));
      } else {
        value = distance(solved.points.at(entity.point_id("start")), solved.points.at(entity.point_id("end")));
      }
    } else if (kind == "radius" || kind == "diameter") {
      const SketchEntity& entity = model.entity(target(0));
      const std::string radius_key = (entity.kind == kCircleKind ? "circle:" : "arc:") + entity.id + ":radius";
      const double* radius = solved.scalars.find(radius_key);
      if (radius == nullptr)
        throw ValueError("No solved radius for '" + entity.id + "'");
      value = *radius * (kind == "diameter" ? 2.0 : 1.0);
    } else if (kind == "major_radius" || kind == "minor_radius") {
      const SketchEntity& ellipse = model.entity(target(0));
      value = distance(solved.points.at(ellipse.point_id("center")),
                       solved.points.at(ellipse.point_id(kind == "major_radius" ? "major" : "minor")));
    } else if (kind == "angle") {
      std::array<SketchPoint2, 2> directions{};
      for (std::size_t i = 0; i < 2; ++i) {
        const SketchEntity& entity = model.entity(target(i));
        const SketchPoint2 start = solved.points.at(entity.point_id("start"));
        const SketchPoint2 end = solved.points.at(entity.point_id("end"));
        directions[i] = {end.first - start.first, end.second - start.second};
      }
      const double cross = directions[0].first * directions[1].second - directions[0].second * directions[1].first;
      const double dot = directions[0].first * directions[1].first + directions[0].second * directions[1].second;
      value = positive_mod(std::atan2(cross, dot) * 180.0 / kPi, 360.0);
    } else if (kind == "line_distance") {
      const SketchEntity& b = model.entity(target(1));
      const SketchPoint2 b_start = solved.points.at(b.point_id("start"));
      const SketchPoint2 b_end = solved.points.at(b.point_id("end"));
      const SketchPoint2 probe = solved.points.at(model.entity(target(0)).point_id("start"));
      const double dx = b_end.first - b_start.first;
      const double dy = b_end.second - b_start.second;
      const double length = std::hypot(dx, dy);
      if (length <= 1e-18)
        throw ValueError("A line-distance measurement requires a non-degenerate line");
      value = std::abs((dx * (probe.second - b_start.second) - dy * (probe.first - b_start.first)) / length);
    } else {
      throw ValueError("Constraint kind '" + kind + "' cannot be used as a reference measurement");
    }
    solved.scalars.set(key, value);
  }
}

}  // namespace scad::sketch_solver
