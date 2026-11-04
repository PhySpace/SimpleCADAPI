// Python bindings for editing existing curves and surfaces (src/cpp/src/surface/editing): read the NURBS data of an
// Edge / Face, change poles, weights, knots and degrees as recorded operations that return a new shape, rebuild, and
// sample curvature / isocurves for an editor.  The names are also in `simplecadapi.surface`.
#include "bindings.hpp"

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/surface/editing.hpp"

namespace {

using namespace scad;
using scad::pybind::Choice;
using scad::pybind::Count;
using scad::pybind::PointVec3;

struct DirectionTag {
  static constexpr auto name = py::detail::const_name("Literal['U', 'V']");
};
using PointRows = std::vector<std::vector<PointVec3>>;

PointGrid grid_of(const PointRows& rows) {
  PointGrid grid;
  grid.reserve(rows.size());
  for (const auto& row : rows)
    grid.emplace_back(row.begin(), row.end());
  return grid;
}

std::optional<int> count_of(const std::optional<Count>& count) {
  return count ? std::optional<int>(count->value) : std::nullopt;
}

}  // namespace

void bind_surface_editing(py::module_& m) {
  // ---- read ----------------------------------------------------------------------------------------------------
  m.def("inspect_curve_rcurvedata", &inspect_curve_rcurvedata, py::arg("edge"),
        "Read the NURBS data of an edge's curve (degree, poles, weights, knots); not recorded.");
  m.def("inspect_surface_rsurfacedata", &inspect_surface_rsurfacedata, py::arg("face"),
        "Read the NURBS data of a face's surface (degrees, pole grid, weights, knots, trimming); not recorded.");

  // ---- conversion ------------------------------------------------------------------------------------------------
  m.def(
      "convert_to_bspline_redge",
      [](const Edge& edge, const TagPrefix& tag_prefix) { return convert_to_bspline_redge(edge, tag_prefix); },
      py::arg("edge"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Convert an edge's curve (line, circle, ...) to a B-spline, as a recorded step.");
  m.def(
      "convert_to_bspline_rface",
      [](const Face& face, const TagPrefix& tag_prefix) { return convert_to_bspline_rface(face, tag_prefix); },
      py::arg("face"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Convert a face's surface (plane, cylinder, ...) to a B-spline, as a recorded step.");

  // ---- curve edits -----------------------------------------------------------------------------------------------
  m.def(
      "set_curve_poles_redge",
      [](const Edge& edge, const std::vector<PointVec3>& poles, const TagPrefix& tag_prefix) {
        return set_curve_poles_redge(edge, {poles.begin(), poles.end()}, tag_prefix);
      },
      py::arg("edge"), py::arg("poles"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new edge whose B-spline has these poles (all of them, in order).");
  m.def(
      "move_curve_poles_redge",
      [](const Edge& edge, const std::map<int, PointVec3>& moves, const TagPrefix& tag_prefix) {
        return move_curve_poles_redge(edge, {moves.begin(), moves.end()}, tag_prefix);
      },
      py::arg("edge"), py::arg("moves"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new edge with some poles moved: {pole index: new position}.");
  m.def(
      "set_curve_weights_redge",
      [](const Edge& edge, const std::vector<double>& weights, const TagPrefix& tag_prefix) {
        return set_curve_weights_redge(edge, weights, tag_prefix);
      },
      py::arg("edge"), py::arg("weights"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new edge whose B-spline has these weights (one per pole).");
  m.def(
      "insert_curve_knot_redge",
      [](const Edge& edge, double parameter, const Count& multiplicity, const TagPrefix& tag_prefix) {
        return insert_curve_knot_redge(edge, parameter, multiplicity, tag_prefix);
      },
      py::arg("edge"), py::arg("parameter"), py::arg("multiplicity") = Count{1}, py::kw_only(),
      py::arg("tag_prefix") = py::none(), "Return a new edge with a knot inserted (the shape does not change).");
  m.def(
      "elevate_curve_degree_redge",
      [](const Edge& edge, const Count& degree, const TagPrefix& tag_prefix) {
        return elevate_curve_degree_redge(edge, degree, tag_prefix);
      },
      py::arg("edge"), py::arg("degree"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new edge with the curve's degree raised (the shape does not change).");

  // ---- surface edits ---------------------------------------------------------------------------------------------
  m.def(
      "set_surface_poles_rface",
      [](const Face& face, const PointRows& poles, const TagPrefix& tag_prefix) {
        return set_surface_poles_rface(face, grid_of(poles), tag_prefix);
      },
      py::arg("face"), py::arg("poles"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new face whose B-spline surface has this pole grid; the trimming is kept.");
  m.def(
      "move_surface_poles_rface",
      [](const Face& face, const std::map<std::pair<int, int>, PointVec3>& moves, const TagPrefix& tag_prefix) {
        return move_surface_poles_rface(face, {moves.begin(), moves.end()}, tag_prefix);
      },
      py::arg("face"), py::arg("moves"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new face with some poles moved: {(row, column): new position}; the trimming is kept.");
  m.def(
      "set_surface_weights_rface",
      [](const Face& face, const WeightGrid& weights, const TagPrefix& tag_prefix) {
        return set_surface_weights_rface(face, weights, tag_prefix);
      },
      py::arg("face"), py::arg("weights"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Return a new face whose B-spline surface has these weights (one per pole); the trimming is kept.");
  m.def(
      "insert_surface_knot_rface",
      [](const Face& face, const Choice<DirectionTag>& direction, double parameter, const Count& multiplicity,
         const TagPrefix& tag_prefix) {
        return insert_surface_knot_rface(face, direction.value, parameter, multiplicity, tag_prefix);
      },
      py::arg("face"), py::arg("direction"), py::arg("parameter"), py::arg("multiplicity") = Count{1}, py::kw_only(),
      py::arg("tag_prefix") = py::none(), "Return a new face with a U or V knot inserted (the shape does not change).");
  m.def(
      "elevate_surface_degree_rface",
      [](const Face& face, const std::optional<Count>& u_degree, const std::optional<Count>& v_degree,
         const TagPrefix& tag_prefix) {
        return elevate_surface_degree_rface(face, count_of(u_degree), count_of(v_degree), tag_prefix);
      },
      py::arg("face"), py::arg("u_degree") = py::none(), py::arg("v_degree") = py::none(), py::kw_only(),
      py::arg("tag_prefix") = py::none(), "Return a new face with the surface's U and/or V degree raised.");

  // ---- rebuild ---------------------------------------------------------------------------------------------------
  m.def(
      "rebuild_curve_redge",
      [](const Edge& edge, const Count& degree, const std::optional<Count>& pole_count, double tolerance,
         const TagPrefix& tag_prefix) {
        return rebuild_curve_redge(
            edge,
            {.degree = degree, .pole_count = count_of(pole_count), .tolerance = tolerance, .tag_prefix = tag_prefix});
      },
      py::arg("edge"), py::arg("degree") = Count{3}, py::arg("pole_count") = py::none(), py::kw_only(),
      py::arg("tolerance") = 1e-3, py::arg("tag_prefix") = py::none(),
      "Refit an edge's curve as a B-spline of the given degree and pole count (or within tolerance).");
  m.def(
      "rebuild_surface_rface",
      [](const Face& face, const Count& u_degree, const Count& v_degree, const std::optional<Count>& u_pole_count,
         const std::optional<Count>& v_pole_count, double tolerance, const TagPrefix& tag_prefix) {
        return rebuild_surface_rface(face, {.u_degree = u_degree,
                                            .v_degree = v_degree,
                                            .u_pole_count = count_of(u_pole_count),
                                            .v_pole_count = count_of(v_pole_count),
                                            .tolerance = tolerance,
                                            .tag_prefix = tag_prefix});
      },
      py::arg("face"), py::arg("u_degree") = Count{3}, py::arg("v_degree") = Count{3},
      py::arg("u_pole_count") = py::none(), py::arg("v_pole_count") = py::none(), py::kw_only(),
      py::arg("tolerance") = 1e-3, py::arg("tag_prefix") = py::none(),
      "Refit a face's surface as a B-spline of the given degrees and pole counts (or within tolerance).");

  // ---- evaluation ------------------------------------------------------------------------------------------------
  m.def(
      "sample_curve_rcurvature",
      [](const Edge& edge, const Count& count) { return sample_curve_rcurvature(edge, count); }, py::arg("edge"),
      py::arg("count") = Count{64}, "Sample points, tangents, normals and curvature along an edge; not recorded.");
  m.def(
      "sample_surface_risocurves",
      [](const Face& face, const Count& u_count, const Count& v_count, const Count& samples) {
        return sample_surface_risocurves(face, u_count, v_count, samples);
      },
      py::arg("face"), py::arg("u_count") = Count{5}, py::arg("v_count") = Count{5}, py::arg("samples") = Count{48},
      "Sample isocurves of a face, clipped to its trimming; not recorded.");

  py::module_ ns = m.attr("surface").cast<py::module_>();
  for (const char* name :
       {"inspect_curve_rcurvedata", "inspect_surface_rsurfacedata", "convert_to_bspline_redge",
        "convert_to_bspline_rface", "set_curve_poles_redge", "move_curve_poles_redge", "set_curve_weights_redge",
        "insert_curve_knot_redge", "elevate_curve_degree_redge", "set_surface_poles_rface", "move_surface_poles_rface",
        "set_surface_weights_rface", "insert_surface_knot_rface", "elevate_surface_degree_rface", "rebuild_curve_redge",
        "rebuild_surface_rface", "sample_curve_rcurvature", "sample_surface_risocurves"})
    ns.attr(name) = m.attr(name);
}
