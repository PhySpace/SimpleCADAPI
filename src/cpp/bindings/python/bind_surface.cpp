// Python bindings for the "surface" area: the surface and shell operators of
// simplecadapi.surface, under the Python SDK's names and keyword signatures.
//
// Every name is also reachable as `simplecadapi._cpp.surface.<name>` (the same object), as in
// the Python package.  This is also where the units hook of the surface area is wired to the
// reactive area's dimension inference.
#include "bindings.hpp"

#include <array>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Circ.hxx>

#include "scad/reactive/expr.hpp"
#include "scad/reactive/units.hpp"
#include "scad/surface/hooks.hpp"
#include "scad/surface/operators.hpp"
#include "scad/surface/types.hpp"

namespace {

using namespace scad;

// expression_uses_units / infer_dimension for the surface operators' dimension checks.
ScalarUnits probe_units(const Scalar& value) {
  const auto node = reactive::lift_scalar(value);
  ScalarUnits units;
  units.uses_units = reactive::expression_uses_units(node);
  if (!units.uses_units) return units;
  const std::optional<reactive::Dimension> dimension = reactive::infer_dimension(node);
  if (dimension && dimension->is_dimensionless()) units.dimension = UnitDimension::Dimensionless;
  else if (dimension && *dimension == reactive::kLength) units.dimension = UnitDimension::Length;
  else units.dimension = UnitDimension::Other;
  return units;
}

// Raw OpenCASCADE builders for the test suite: the ops_geometry operators are the real way to
// make edges and wires, but the surface tests must not wait for them.
void bind_surface_testing(py::module_& m) {
  py::module_ t = m.def_submodule("_surface_testing", "edge/wire builders for the surface tests");
  const auto pnt = [](const Vec3& v) { return gp_Pnt(v.x, v.y, v.z); };
  t.def("line", [pnt](const Vec3& a, const Vec3& b) { return Edge(BRepBuilderAPI_MakeEdge(pnt(a), pnt(b)).Edge()); });
  t.def("arc", [pnt](const Vec3& a, const Vec3& b, const Vec3& c) {
    return Edge(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(pnt(a), pnt(b), pnt(c)).Value()).Edge());
  });
  t.def("spline", [pnt](const std::vector<Vec3>& points, double tolerance) {
    Handle(TColgp_HArray1OfPnt) array = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
    for (std::size_t i = 0; i < points.size(); ++i) array->SetValue(static_cast<int>(i) + 1, pnt(points[i]));
    GeomAPI_Interpolate interpolation(array, false, tolerance);
    interpolation.Perform();
    return Edge(BRepBuilderAPI_MakeEdge(interpolation.Curve()).Edge());
  }, py::arg("points"), py::arg("tolerance") = 1e-5);
  t.def("wire", [](const std::vector<Edge>& edges) {
    BRepBuilderAPI_MakeWire builder;
    for (const Edge& e : edges) builder.Add(TopoDS::Edge(e.wrapped()));
    return Wire(builder.Wire());
  });
  t.def("polygon", [pnt](const std::vector<Vec3>& points, bool closed) {
    BRepBuilderAPI_MakePolygon builder;
    for (const Vec3& p : points) builder.Add(pnt(p));
    if (closed) builder.Close();
    return Wire(builder.Wire());
  }, py::arg("points"), py::arg("closed") = true);
  t.def("rectangle", [](double width, double height, const Vec3& center) {
    BRepBuilderAPI_MakePolygon builder;
    for (const auto& [dx, dy] : {std::pair{-0.5, -0.5}, std::pair{0.5, -0.5}, std::pair{0.5, 0.5}, std::pair{-0.5, 0.5}})
      builder.Add(gp_Pnt(center.x + dx * width, center.y + dy * height, center.z));
    builder.Close();
    return Wire(builder.Wire());
  }, py::arg("width"), py::arg("height"), py::arg("center") = Vec3{0, 0, 0});
  t.def("circle", [](const Vec3& center, double radius) {
    const gp_Circ circle(gp_Ax2(gp_Pnt(center.x, center.y, center.z), gp_Dir(0, 0, 1)), radius);
    return Wire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire());
  });
  t.def("point", [](double x, double y, double z) { return Vertex(BRepBuilderAPI_MakeVertex(gp_Pnt(x, y, z)).Vertex()); });
  t.def("is_valid", [](const Shape& shape) { return BRepCheck_Analyzer(shape.wrapped()).IsValid(); });
  t.def("bbox", [](const Shape& shape) {
    const auto b = shape.bounding_box();
    return std::array<double, 6>{b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax};
  });
}

}  // namespace

void bind_surface(py::module_& m) {
  using namespace scad;
  set_scalar_units_probe(&probe_units);
  bind_surface_testing(m);

  // ---- value types ---------------------------------------------------------------------------
  py::class_<SurfaceBoundary>(m, "SurfaceBoundary", "One edge constraint used by make_surface_patch_rface.")
      .def(py::init([](Edge edge, const std::string& continuity, std::optional<Face> support) {
             return SurfaceBoundary(std::move(edge), continuity, std::move(support));
           }),
           py::arg("edge"), py::arg("continuity") = "C0", py::arg("support") = py::none())
      .def_property_readonly("edge", [](const SurfaceBoundary& b) { return b.edge; })
      .def_property_readonly("continuity", [](const SurfaceBoundary& b) { return b.continuity; })
      .def_property_readonly("support", [](const SurfaceBoundary& b) { return b.support; })
      .def("as_dict", &SurfaceBoundary::as_dict);

  py::class_<SurfaceFillingSettings>(m, "SurfaceFillingSettings",
                                     "Explicit OCCT filling controls; units are model units and radians.")
      .def(py::init([](double degree, double points_per_curve, double iterations, bool anisotropic, double tolerance_2d,
                       double tolerance_3d, double angular_tolerance, double curvature_tolerance, double max_degree,
                       double max_segments) {
             // The SDK's dataclass does not check types: a replayed payload carries 3.0 for 3.
             const auto whole = [](double v) { return static_cast<int>(v); };
             SurfaceFillingSettings settings{whole(degree),     whole(points_per_curve), whole(iterations), anisotropic,
                                             tolerance_2d,      tolerance_3d,            angular_tolerance,
                                             curvature_tolerance, whole(max_degree),     whole(max_segments)};
             settings.validate();
             return settings;
           }),
           py::arg("degree") = 3, py::arg("points_per_curve") = 15, py::arg("iterations") = 2,
           py::arg("anisotropic") = false, py::arg("tolerance_2d") = 1e-5, py::arg("tolerance_3d") = 1e-4,
           py::arg("angular_tolerance") = 0.01, py::arg("curvature_tolerance") = 0.1, py::arg("max_degree") = 8,
           py::arg("max_segments") = 9)
      .def_readonly("degree", &SurfaceFillingSettings::degree)
      .def_readonly("points_per_curve", &SurfaceFillingSettings::points_per_curve)
      .def_readonly("iterations", &SurfaceFillingSettings::iterations)
      .def_readonly("anisotropic", &SurfaceFillingSettings::anisotropic)
      .def_readonly("tolerance_2d", &SurfaceFillingSettings::tolerance_2d)
      .def_readonly("tolerance_3d", &SurfaceFillingSettings::tolerance_3d)
      .def_readonly("angular_tolerance", &SurfaceFillingSettings::angular_tolerance)
      .def_readonly("curvature_tolerance", &SurfaceFillingSettings::curvature_tolerance)
      .def_readonly("max_degree", &SurfaceFillingSettings::max_degree)
      .def_readonly("max_segments", &SurfaceFillingSettings::max_segments)
      .def("as_dict", &SurfaceFillingSettings::as_dict)
      .def("__eq__", [](const SurfaceFillingSettings& a, const SurfaceFillingSettings& b) { return a == b; });

  // ---- operators -----------------------------------------------------------------------------
  m.def(
      "make_bezier_surface_rface",
      [](const PointGrid& control_points, const std::optional<WeightGrid>& weights, const TagPrefix& tag_prefix) {
        return make_bezier_surface_rface(control_points, weights, tag_prefix);
      },
      py::arg("control_points"), py::arg("weights") = py::none(), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Create a trimmed Face carrying a tensor-product Bezier surface.");

  m.def(
      "make_cylindrical_surface_rface",
      [](const Scalar& radius, const ScalarRange& u_range, const ScalarRange& v_range, const ScalarVec3& origin,
         const ScalarVec3& axis, const std::optional<ScalarVec3>& x_direction, const Scalar& tolerance,
         const TagPrefix& tag_prefix) {
        return make_cylindrical_surface_rface(
            radius, u_range, v_range,
            {.origin = origin, .axis = axis, .x_direction = x_direction, .tolerance = tolerance, .tag_prefix = tag_prefix});
      },
      py::arg("radius"), py::arg("u_range"), py::arg("v_range"),
      py::arg("origin") = ScalarVec3{0.0, 0.0, 0.0}, py::arg("axis") = ScalarVec3{0.0, 0.0, 1.0},
      py::arg("x_direction") = py::none(), py::kw_only(), py::arg("tolerance") = Scalar(1e-7),
      py::arg("tag_prefix") = py::none(),
      "Create a finite cylindrical carrier Face over explicit U/V ranges (U in raw radians, at most one turn).");

  m.def(
      "fit_point_grid_rface",
      [](const PointGrid& points, double tolerance, int degree_min, int degree_max,
         const std::optional<std::array<double, 3>>& smoothing, const TagPrefix& tag_prefix) {
        return fit_point_grid_rface(points, {.tolerance = tolerance,
                                             .degree_min = degree_min,
                                             .degree_max = degree_max,
                                             .smoothing = smoothing,
                                             .tag_prefix = tag_prefix});
      },
      py::arg("points"), py::kw_only(), py::arg("tolerance") = 1e-3, py::arg("degree_min") = 3,
      py::arg("degree_max") = 8, py::arg("smoothing") = py::none(), py::arg("tag_prefix") = py::none(),
      "Fit a B-spline Face through a rectangular 3D point grid.");

  m.def(
      "make_ruled_surface_rface",
      [](const Edge& edge_a, const Edge& edge_b, const TagPrefix& tag_prefix) {
        return make_ruled_surface_rface(edge_a, edge_b, tag_prefix);
      },
      py::arg("edge_a"), py::arg("edge_b"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Create a ruled Face spanning two compatible edges.");

  m.def(
      "make_gordon_surface_rface",
      [](const std::vector<Edge>& profiles, const std::vector<Edge>& guides, double tolerance,
         const TagPrefix& tag_prefix) { return make_gordon_surface_rface(profiles, guides, tolerance, tag_prefix); },
      py::arg("profiles"), py::arg("guides"), py::kw_only(), py::arg("tolerance") = 1e-3,
      py::arg("tag_prefix") = py::none(),
      "Create a Gordon Face from intersecting profile and guide edge networks.");

  m.def(
      "make_surface_patch_rface",
      [](const std::vector<SurfaceBoundary>& boundaries, const std::vector<Vec3>& points,
         const std::optional<SurfaceFillingSettings>& settings, const std::vector<Wire>& holes,
         const TagPrefix& tag_prefix) {
        return make_surface_patch_rface(
            boundaries, {.points = points, .settings = settings, .holes = holes, .tag_prefix = tag_prefix});
      },
      py::arg("boundaries"), py::kw_only(), py::arg("points") = std::vector<Vec3>{},
      py::arg("settings") = py::none(), py::arg("holes") = std::vector<Wire>{}, py::arg("tag_prefix") = py::none(),
      "Fill a constrained boundary network into one Face, optionally with holes.");

  m.def(
      "trim_surface_rface",
      [](const Face& carrier, const Wire& outer, const std::vector<Wire>& holes, double tolerance,
         const TagPrefix& tag_prefix) {
        return trim_surface_rface(carrier, outer, {.holes = holes, .tolerance = tolerance, .tag_prefix = tag_prefix});
      },
      py::arg("carrier"), py::arg("outer"), py::arg("holes") = std::vector<Wire>{}, py::kw_only(),
      py::arg("tolerance") = 1e-7, py::arg("tag_prefix") = py::none(),
      "Trim a carrier Face to exactly one connected Face.");

  m.def(
      "loft_rshell",
      [](const std::vector<py::object>& raw_sections, bool ruled, const TagPrefix& tag_prefix,
         const std::optional<std::string>& result_tag, const std::optional<std::string>& start_wire_tag,
         const std::optional<std::string>& end_wire_tag, const std::optional<std::string>& side_faces_tag) {
        std::vector<LoftSection> sections;
        sections.reserve(raw_sections.size());
        for (const py::object& item : raw_sections) {
          if (py::isinstance<Wire>(item)) sections.emplace_back(item.cast<Wire>());
          else if (py::isinstance<Vertex>(item)) sections.emplace_back(item.cast<Vertex>());
          else throw TypeError("loft_rshell sections must contain only Wire or Vertex objects");
        }
        return loft_rshell(sections, ruled,
                           {.tag_prefix = tag_prefix,
                            .result_tag = result_tag,
                            .start_wire_tag = start_wire_tag,
                            .end_wire_tag = end_wire_tag,
                            .side_faces_tag = side_faces_tag});
      },
      py::arg("sections"), py::kw_only(), py::arg("ruled") = false, py::arg("tag_prefix") = py::none(),
      py::arg("result_tag") = py::none(), py::arg("start_wire_tag") = py::none(),
      py::arg("end_wire_tag") = py::none(), py::arg("side_faces_tag") = py::none(),
      "Create an open loft Shell with endpoint-Wire and side-Face naming.");

  m.def(
      "sew_faces_rshell",
      [](const std::vector<Face>& faces, double tolerance, const TagPrefix& tag_prefix) {
        return sew_faces_rshell(faces, tolerance, tag_prefix);
      },
      py::arg("faces"), py::kw_only(), py::arg("tolerance") = 1e-6, py::arg("tag_prefix") = py::none(),
      "Sew faces into exactly one connected Shell.");

  m.def(
      "make_solid_from_shell_rsolid",
      [](const Shell& shell, const TagPrefix& tag_prefix) { return make_solid_from_shell_rsolid(shell, tag_prefix); },
      py::arg("shell"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Create an oriented Solid from one valid closed Shell.");

  m.def(
      "free_boundaries_rwirelist",
      [](const Shell& shell, double tolerance) { return free_boundaries_rwirelist(shell, tolerance); },
      py::arg("shell"), py::kw_only(), py::arg("tolerance") = 1e-6,
      "Return unique closed and open free boundary wires of a Shell.");

  m.def(
      "fill_holes_rshell",
      [](const Shell& shell, const std::optional<std::vector<int>>& hole_indices, double tolerance,
         const std::optional<SurfaceFillingSettings>& settings, const TagPrefix& tag_prefix) {
        return fill_holes_rshell(shell, {.hole_indices = hole_indices,
                                         .tolerance = tolerance,
                                         .settings = settings,
                                         .tag_prefix = tag_prefix});
      },
      py::arg("shell"), py::arg("hole_indices") = py::none(), py::kw_only(), py::arg("tolerance") = 1e-6,
      py::arg("settings") = py::none(), py::arg("tag_prefix") = py::none(),
      "Fill selected closed free boundaries and return a sewn Shell.");

  // simplecadapi.surface: the same objects under the namespace the Python package offers.
  py::module_ ns = m.def_submodule("surface", "Surface modeling namespace (the same functions as the top level).");
  for (const char* name :
       {"SurfaceBoundary", "SurfaceFillingSettings", "make_bezier_surface_rface", "make_cylindrical_surface_rface",
        "fit_point_grid_rface", "make_ruled_surface_rface", "make_gordon_surface_rface", "make_surface_patch_rface",
        "loft_rshell", "trim_surface_rface", "sew_faces_rshell", "make_solid_from_shell_rsolid",
        "free_boundaries_rwirelist", "fill_holes_rshell"})
    ns.attr(name) = m.attr(name);
}
