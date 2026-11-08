// set_surface_poles_rface, move_surface_poles_rface, set_surface_weights_rface, insert_surface_knot_rface,
// elevate_surface_degree_rface: edits of a face's B-spline surface that keep its parametrisation, so the face keeps
// its trimming loops in (u, v).
#include <algorithm>
#include <cmath>
#include <string>

#include "access.hpp"
#include "finish.hpp"
#include "scad/surface/editing.hpp"

namespace scad {

using namespace surface::editing;

namespace {

ErrorSpec surface_spec(const char* op, const char* what) {
  return ErrorSpec{op,
                   what,
                   {"The face does not carry a B-spline or Bezier surface.", "An argument does not fit the surface.",
                    "The edited surface folds the face's boundary."},
                   {"Convert analytic faces (planes, cylinders) with convert_to_bspline_rface first.",
                    "Read the surface with inspect_surface_rsurfacedata: pole grid, degrees, knots, domain."}};
}

std::string grid_text(int rows, int columns) {
  return std::to_string(rows) + " x " + std::to_string(columns);
}

int existing_multiplicity(const TColStd_Array1OfReal& knots, const TColStd_Array1OfInteger& mults, double parameter) {
  for (int i = knots.Lower(); i <= knots.Upper(); ++i)
    if (std::abs(knots(i) - parameter) <= 1e-9 * std::max(1.0, std::abs(parameter)))
      return mults(i);
  return 0;
}

}  // namespace

Face set_surface_poles_rface(const Face& face, const PointGrid& poles, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = surface_spec("set_surface_poles_rface", "Failed to set the poles of the surface.");
  return edit_scope(kSpec, [&] {
    EditableSurface s = editable_surface(face);
    const int rows = s.surface->NbUPoles(), columns = s.surface->NbVPoles();
    const bool shaped = static_cast<int>(poles.size()) == rows &&
                        std::all_of(poles.begin(), poles.end(),
                                    [&](const auto& row) { return static_cast<int>(row.size()) == columns; });
    if (!shaped)
      throw ValueError("poles must be a " + grid_text(rows, columns) +
                       " grid (rows along U, as inspect_surface_rsurfacedata reports it)");
    Value::Array recorded;
    for (int i = 0; i < rows; ++i) {
      Value::Array row;
      for (int j = 0; j < columns; ++j) {
        const Vec3& p = poles[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)];
        require_finite(p, "poles");
        s.surface->SetPole(i + 1, j + 1, rep_point(p, s.location));
        row.push_back(point_value(p));
      }
      recorded.emplace_back(std::move(row));
    }
    Value params = Value::object();
    params.set("poles", Value(std::move(recorded)));
    return finish_face(face, "set_surface_poles_rface", std::move(params), tag_prefix, s.surface, s.location);
  });
}

Face move_surface_poles_rface(const Face& face, const std::map<std::pair<int, int>, Vec3>& moves,
                              const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = surface_spec("move_surface_poles_rface", "Failed to move poles of the surface.");
  return edit_scope(kSpec, [&] {
    EditableSurface s = editable_surface(face);
    if (moves.empty())
      throw ValueError("moves must name at least one pole");
    const int rows = s.surface->NbUPoles(), columns = s.surface->NbVPoles();
    Value::Array recorded;
    for (const auto& [index, position] : moves) {
      const auto [i, j] = index;
      if (i < 0 || i >= rows || j < 0 || j >= columns)
        throw ValueError("pole index (" + std::to_string(i) + ", " + std::to_string(j) +
                         ") is out of range: the pole grid is " + grid_text(rows, columns) + " (0-based indices)");
      require_finite(position, "moves");
      s.surface->SetPole(i + 1, j + 1, rep_point(position, s.location));
      recorded.emplace_back(Value::Array{i, j, point_value(position)});
    }
    Value params = Value::object();
    params.set("moves", Value(std::move(recorded)));
    return finish_face(face, "move_surface_poles_rface", std::move(params), tag_prefix, s.surface, s.location);
  });
}

Face set_surface_weights_rface(const Face& face, const WeightGrid& weights, const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = surface_spec("set_surface_weights_rface", "Failed to set the weights of the surface.");
  return edit_scope(kSpec, [&] {
    EditableSurface s = editable_surface(face);
    const int rows = s.surface->NbUPoles(), columns = s.surface->NbVPoles();
    const bool shaped = static_cast<int>(weights.size()) == rows &&
                        std::all_of(weights.begin(), weights.end(),
                                    [&](const auto& row) { return static_cast<int>(row.size()) == columns; });
    if (!shaped)
      throw ValueError("weights must be a " + grid_text(rows, columns) + " grid (one weight per pole)");
    Value::Array recorded;
    for (int i = 0; i < rows; ++i) {
      Value::Array row;
      for (int j = 0; j < columns; ++j) {
        const double w = weights[static_cast<std::size_t>(i)][static_cast<std::size_t>(j)];
        if (!std::isfinite(w) || w <= 0.0)
          throw ValueError("weights must be positive finite values");
        s.surface->SetWeight(i + 1, j + 1, w);
        row.emplace_back(w);
      }
      recorded.emplace_back(std::move(row));
    }
    Value params = Value::object();
    params.set("weights", Value(std::move(recorded)));
    return finish_face(face, "set_surface_weights_rface", std::move(params), tag_prefix, s.surface, s.location);
  });
}

Face insert_surface_knot_rface(const Face& face, const std::string& direction, double parameter, int multiplicity,
                               const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec = surface_spec("insert_surface_knot_rface", "Failed to insert a knot into the surface.");
  return edit_scope(kSpec, [&] {
    if (direction != "U" && direction != "V")
      throw ValueError("direction must be 'U' or 'V'");
    EditableSurface s = editable_surface(face);
    const bool along_u = direction == "U";
    double u1 = 0, u2 = 0, v1 = 0, v2 = 0;
    s.surface->Bounds(u1, u2, v1, v2);
    const double low = along_u ? u1 : v1, high = along_u ? u2 : v2;
    if (!std::isfinite(parameter) || parameter <= low || parameter >= high)
      throw ValueError("parameter must lie strictly inside the surface's " + direction + " domain [" +
                       std::to_string(low) + ", " + std::to_string(high) + "]");
    const int degree = along_u ? s.surface->UDegree() : s.surface->VDegree();
    const int existing = along_u ? existing_multiplicity(s.surface->UKnots(), s.surface->UMultiplicities(), parameter)
                                 : existing_multiplicity(s.surface->VKnots(), s.surface->VMultiplicities(), parameter);
    if (multiplicity < 1 || multiplicity + existing > degree)
      throw ValueError("multiplicity must be at least 1 and the knot's total multiplicity at most the " + direction +
                       " degree (" + std::to_string(degree) + ")");
    if (along_u)
      s.surface->InsertUKnot(parameter, multiplicity, 1e-9, Standard_True);
    else
      s.surface->InsertVKnot(parameter, multiplicity, 1e-9, Standard_True);
    Value params = Value::object();
    params.set("direction", direction);
    params.set("parameter", parameter);
    params.set("multiplicity", multiplicity);
    return finish_face(face, "insert_surface_knot_rface", std::move(params), tag_prefix, s.surface, s.location);
  });
}

Face elevate_surface_degree_rface(const Face& face, std::optional<int> u_degree, std::optional<int> v_degree,
                                  const TagPrefix& tag_prefix) {
  static const ErrorSpec kSpec =
      surface_spec("elevate_surface_degree_rface", "Failed to elevate the degree of the surface.");
  return edit_scope(kSpec, [&] {
    if (!u_degree && !v_degree)
      throw ValueError("give u_degree, v_degree or both");
    EditableSurface s = editable_surface(face);
    const int u = u_degree.value_or(s.surface->UDegree());
    const int v = v_degree.value_or(s.surface->VDegree());
    const int max = Geom_BSplineSurface::MaxDegree();
    if (u < s.surface->UDegree() || v < s.surface->VDegree() || u > max || v > max)
      throw ValueError("a degree cannot be lowered (the surface is " + std::to_string(s.surface->UDegree()) + " x " +
                       std::to_string(s.surface->VDegree()) + ") or exceed " + std::to_string(max));
    if (u == s.surface->UDegree() && v == s.surface->VDegree())
      throw ValueError("the surface already has these degrees; raise at least one of them");
    s.surface->IncreaseDegree(u, v);
    Value params = Value::object();
    params.set("u_degree", u_degree ? Value(*u_degree) : Value());
    params.set("v_degree", v_degree ? Value(*v_degree) : Value());
    return finish_face(face, "elevate_surface_degree_rface", std::move(params), tag_prefix, s.surface, s.location);
  });
}

}  // namespace scad
