// Python bindings for the "ops_geometry" area: the non-surface operators of
// simplecadapi/operators/geometry.py, under the Python names, argument names and
// defaults (keyword-only where Python is keyword-only), plus the create_* aliases.
#include "bindings.hpp"

#include "scad/core/tolerance.hpp"
#include "scad/io/brep_region.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>

#include "scad/ops/geometry/geometry.hpp"
#include "scad/reactive/registry.hpp"

namespace {

using namespace scad;
using namespace pybind11::literals;

// Defaults as Python tuples, so help() shows (0, 0, 1) like the Python SDK.
py::tuple origin() {
  return py::make_tuple(0, 0, 0);
}
py::tuple unit_z() {
  return py::make_tuple(0, 0, 1);
}

// `degree` takes any number: a bool or a fraction is rejected by the operator itself, with
// its own error, as Python does (bool -> NaN is "not an integer").
double degree_of(const py::object& degree) {
  if (PyBool_Check(degree.ptr()))
    return std::nan("");
  return degree.cast<double>();
}

SplineSpec spline_spec(std::vector<ScalarPoint> control_points, const py::object& degree,
                       std::optional<ScalarList> knots, std::optional<std::vector<int>> multiplicities,
                       std::optional<ScalarList> weights, bool periodic) {
  return {.control_points = std::move(control_points),
          .degree = degree_of(degree),
          .knots = std::move(knots),
          .multiplicities = std::move(multiplicities),
          .weights = std::move(weights),
          .periodic = periodic};
}

std::string path_text(const py::object& path) {
  return py::str(py::module_::import("os").attr("fspath")(path)).cast<std::string>();
}

void bind_lines(py::module_& m) {
  m.def("make_point_rvertex", &make_point_rvertex, py::arg("x"), py::arg("y"), py::arg("z"),
        "Create a point in 3D space and return it as a vertex.");
  m.def("make_line_redge", &make_line_redge, py::arg("start"), py::arg("end"), py::kw_only(),
        py::arg("tag_prefix") = py::none(), "Create a straight edge between two points.");
  m.def("make_segment_redge", &make_segment_redge, py::arg("start"), py::arg("end"),
        "Alias of `make_line_redge` that returns a straight edge.");
  m.def("make_segment_rwire", &make_segment_rwire, py::arg("start"), py::arg("end"),
        "Create a wire containing a single straight segment.");
  m.def("make_polyline_rwire", &make_polyline_rwire, py::arg("points"), py::arg("closed") = false,
        "Create a polyline wire from a point list.");
}

void bind_circles(py::module_& m) {
  const auto profile = [](auto fn) {
    return [fn](const Scalar3& center, const Scalar& radius, const Scalar3& normal, OptionalString tag_prefix,
                OptionalString edge_tag) {
      return fn(center, radius, normal, ProfileTags{std::move(tag_prefix), std::move(edge_tag)});
    };
  };
  m.def("make_circle_redge", &make_circle_redge, py::arg("center"), py::arg("radius"), py::arg("normal") = unit_z(),
        py::kw_only(), py::arg("tag_prefix") = py::none(), "Create a circular edge.");
  m.def("make_circle_rwire", profile(&make_circle_rwire), py::arg("center"), py::arg("radius"),
        py::arg("normal") = unit_z(), py::kw_only(), py::arg("tag_prefix") = py::none(),
        py::arg("edge_tag") = py::none(), "Create a circular wire.");
  m.def("make_circle_rface", profile(&make_circle_rface), py::arg("center"), py::arg("radius"),
        py::arg("normal") = unit_z(), py::kw_only(), py::arg("tag_prefix") = py::none(),
        py::arg("edge_tag") = py::none(), "Create a circular face.");

  m.def("make_ellipse_redge", &make_ellipse_redge, py::arg("center"), py::arg("major_radius"), py::arg("minor_radius"),
        py::arg("normal") = unit_z(), py::kw_only(), py::arg("major_direction") = py::none(),
        py::arg("tag_prefix") = py::none(),
        "Create a full ellipse edge.\n\n``major_direction`` orients the major axis in the ellipse plane; when\n"
        "omitted the plane basis derived from ``normal`` picks it.");
  const auto ellipse = [](auto fn) {
    return [fn](const Scalar3& center, const Scalar& major, const Scalar& minor, const Scalar3& normal,
                std::optional<Scalar3> major_direction, OptionalString tag_prefix, OptionalString edge_tag) {
      return fn(center, major, minor, normal,
                EllipseOptions{std::move(major_direction), std::move(tag_prefix), std::move(edge_tag)});
    };
  };
  m.def("make_ellipse_rwire", ellipse(&make_ellipse_rwire), py::arg("center"), py::arg("major_radius"),
        py::arg("minor_radius"), py::arg("normal") = unit_z(), py::kw_only(), py::arg("major_direction") = py::none(),
        py::arg("tag_prefix") = py::none(), py::arg("edge_tag") = py::none(), "Create an elliptical wire.");
  m.def("make_ellipse_rface", ellipse(&make_ellipse_rface), py::arg("center"), py::arg("major_radius"),
        py::arg("minor_radius"), py::arg("normal") = unit_z(), py::kw_only(), py::arg("major_direction") = py::none(),
        py::arg("tag_prefix") = py::none(), py::arg("edge_tag") = py::none(), "Create an elliptical face.");
}

void bind_rectangles(py::module_& m) {
  const auto rectangle = [](auto fn) {
    return [fn](const Scalar& width, const Scalar& height, const Scalar3& center, const Scalar3& normal,
                OptionalString tag_prefix, std::optional<std::vector<std::string>> edge_tags) {
      return fn(width, height, center, normal, RectangleTags{std::move(tag_prefix), std::move(edge_tags)});
    };
  };
  m.def("make_rectangle_rwire", rectangle(&make_rectangle_rwire), py::arg("width"), py::arg("height"),
        py::arg("center") = origin(), py::arg("normal") = unit_z(), py::kw_only(), py::arg("tag_prefix") = py::none(),
        py::arg("edge_tags") = py::none(), "Create a rectangular wire.");
  m.def("make_rectangle_rface", rectangle(&make_rectangle_rface), py::arg("width"), py::arg("height"),
        py::arg("center") = origin(), py::arg("normal") = unit_z(), py::kw_only(), py::arg("tag_prefix") = py::none(),
        py::arg("edge_tags") = py::none(), "Create a rectangular face.");
}

void bind_arcs(py::module_& m) {
  m.def("make_three_point_arc_redge", &make_three_point_arc_redge, py::arg("start"), py::arg("middle"), py::arg("end"),
        "Create an arc edge from three points.");
  m.def("make_three_point_arc_rwire", &make_three_point_arc_rwire, py::arg("start"), py::arg("middle"), py::arg("end"),
        "Create a wire containing an arc defined by three points.");
  m.def("make_angle_arc_redge", &make_angle_arc_redge, py::arg("center"), py::arg("radius"), py::arg("start_angle"),
        py::arg("end_angle"), py::arg("normal") = unit_z(),
        "Create an arc edge from a center, radius, and angle range.");
  m.def("make_angle_arc_rwire", &make_angle_arc_rwire, py::arg("center"), py::arg("radius"), py::arg("start_angle"),
        py::arg("end_angle"), py::arg("normal") = unit_z(),
        "Create a wire containing an arc defined by a center, radius, and angle range.");
}

void bind_splines(py::module_& m) {
  const auto exact = [](auto fn) {
    return [fn](std::vector<ScalarPoint> control_points, const py::object& degree, std::optional<ScalarList> knots,
                std::optional<std::vector<int>> multiplicities, std::optional<ScalarList> weights, bool periodic) {
      return fn(spline_spec(std::move(control_points), degree, std::move(knots), std::move(multiplicities),
                            std::move(weights), periodic));
    };
  };
  m.def("make_spline_redge", exact(&make_spline_redge), py::kw_only(), py::arg("control_points"), py::arg("degree") = 3,
        py::arg("knots") = py::none(), py::arg("multiplicities") = py::none(), py::arg("weights") = py::none(),
        py::arg("periodic") = false,
        "Create an exact B-spline edge from named control-point parameters.\n\n"
        "Pass sampled curve points through `fit_cubic_bspline_control_points(...)` first,\n"
        "then pass the result fields explicitly as `control_points=...`, `knots=...`,\n"
        "and `multiplicities=...`. `control_points` are poles, not interpolation\n"
        "points; the curve generally does not pass through interior poles.");
  m.def("make_spline_rwire", exact(&make_spline_rwire), py::kw_only(), py::arg("control_points"), py::arg("degree") = 3,
        py::arg("knots") = py::none(), py::arg("multiplicities") = py::none(), py::arg("weights") = py::none(),
        py::arg("periodic") = false, "Create a wire containing one exact B-spline edge.");

  const auto interpolated = [](auto fn) {
    return [fn](std::vector<ScalarPoint> points, bool periodic, const Scalar& tolerance) {
      return fn(SplineInterpolation{std::move(points), periodic, tolerance});
    };
  };
  m.def("make_interpolated_spline_redge", interpolated(&make_interpolated_spline_redge), py::kw_only(),
        py::arg("points"), py::arg("periodic") = false, py::arg("tolerance") = tol::kSplineInterpolation,
        "Interpolate an exact B-spline edge through the supplied points.");
  m.def("make_interpolated_spline_rwire", interpolated(&make_interpolated_spline_rwire), py::kw_only(),
        py::arg("points"), py::arg("periodic") = false, py::arg("tolerance") = tol::kSplineInterpolation,
        "Create a one-edge wire that interpolates the supplied points.");
  m.def("make_periodic_spline_rwire", &make_periodic_spline_rwire, py::kw_only(), py::arg("points"),
        py::arg("tolerance") = tol::kSplineInterpolation,
        "Create a closed periodic spline wire interpolating the supplied points.");
}

void bind_helix(py::module_& m) {
  const auto helix = [](auto fn) {
    return
        [fn](const Scalar& pitch, const Scalar& height, const Scalar& radius, const Scalar3& center, const Scalar3& dir,
             const std::string& handedness) { return fn(pitch, height, radius, center, dir, handedness); };
  };
  m.def("make_helix_redge", helix(&make_helix_redge), py::arg("pitch"), py::arg("height"), py::arg("radius"),
        py::arg("center") = origin(), py::arg("dir") = unit_z(), py::kw_only(), py::arg("handedness") = "Right",
        "Create a helix edge, right- or left-handed.");
  m.def("make_helix_rwire", helix(&make_helix_rwire), py::arg("pitch"), py::arg("height"), py::arg("radius"),
        py::arg("center") = origin(), py::arg("dir") = unit_z(), py::kw_only(), py::arg("handedness") = "Right",
        "Create a helix wire, right- or left-handed.");
}

void bind_wires_and_faces(py::module_& m) {
  m.def("make_wire_from_edges_rwire", &make_wire_from_edges_rwire, py::arg("edges"), py::kw_only(),
        py::arg("tag_prefix") = py::none(), "Create a wire from a list of connected edges.");
  m.def("make_face_from_wire_rface", &make_face_from_wire_rface, py::arg("wire"), py::arg("normal") = unit_z(),
        py::kw_only(), py::arg("tag_prefix") = py::none(), "Create a face from a closed wire.");
  m.def(
      "make_face_from_wires_rface",
      [](const Shape& outer, const std::optional<std::vector<Shape>>& inner, const Scalar3& normal) {
        return make_face_from_wires_rface(outer, inner.value_or(std::vector<Shape>{}), normal);
      },
      py::arg("outer_wire"), py::arg("inner_wires"), py::arg("normal") = unit_z(),
      "Create a face from one outer closed wire and optional inner closed wires.");
}

void bind_primitives(py::module_& m) {
  m.def(
      "make_box_rsolid",
      [](const Scalar& width, const Scalar& height, const Scalar& depth, const Scalar3& center,
         OptionalString tag_prefix, OptionalString result_tag, OptionalString bottom, OptionalString top,
         OptionalString front, OptionalString back, OptionalString left, OptionalString right) {
        return make_box_rsolid(width, height, depth, center,
                               BoxTags{std::move(tag_prefix), std::move(result_tag), std::move(bottom), std::move(top),
                                       std::move(front), std::move(back), std::move(left), std::move(right)});
      },
      py::arg("width"), py::arg("height"), py::arg("depth"), py::arg("bottom_face_center") = origin(), py::kw_only(),
      py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(), py::arg("bottom_face_tag") = py::none(),
      py::arg("top_face_tag") = py::none(), py::arg("front_face_tag") = py::none(),
      py::arg("back_face_tag") = py::none(), py::arg("left_face_tag") = py::none(),
      py::arg("right_face_tag") = py::none(),
      "Create a box with native kernel-backed Face topology tags.\n\n"
      "The box extends ``depth`` along the current coordinate-system z_axis\n"
      "starting at the bottom face; ``width`` spans the x_axis and ``height``\n"
      "spans the y_axis.\n\n"
      "Args:\n"
      "    width: Box size along the current coordinate-system x_axis.\n"
      "    height: Box size along the current coordinate-system y_axis.\n"
      "    depth: Box size along the current coordinate-system z_axis.\n"
      "    bottom_face_center: Geometric center of the box's bottom face in the\n"
      "        current coordinate system. The box is centered on this point\n"
      "        along x and y (it spans width/2 and height/2 to each side) and\n"
      "        extends the full ``depth`` upward along the z_axis from this\n"
      "        point's height. It is not a corner; to build a box\n"
      "        occupying x in [0, w], pass ``bottom_face_center=(w/2, h/2, z0)``.");

  const auto axial_tags = [](OptionalString tag_prefix, OptionalString result_tag, OptionalString start_face,
                             OptionalString end_face, OptionalString side_face, OptionalString start_edge,
                             OptionalString end_edge, OptionalString seam_edge) {
    return AxialSolidTags{std::move(tag_prefix), std::move(result_tag), std::move(start_face), std::move(end_face),
                          std::move(side_face),  std::move(start_edge), std::move(end_edge),   std::move(seam_edge)};
  };
  m.def(
      "make_cylinder_rsolid",
      [axial_tags](const Scalar& radius, const Scalar& height, const Scalar3& center, const Scalar3& axis,
                   OptionalString tag_prefix, OptionalString result_tag, OptionalString start_face,
                   OptionalString end_face, OptionalString side_face, OptionalString start_edge,
                   OptionalString end_edge, OptionalString seam_edge) {
        return make_cylinder_rsolid(
            radius, height, center, axis,
            axial_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face), std::move(end_face),
                       std::move(side_face), std::move(start_edge), std::move(end_edge), std::move(seam_edge)));
      },
      py::arg("radius"), py::arg("height"), py::arg("bottom_face_center") = origin(), py::arg("axis") = unit_z(),
      py::kw_only(), py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(),
      py::arg("start_face_tag") = py::none(), py::arg("end_face_tag") = py::none(),
      py::arg("side_face_tag") = py::none(), py::arg("start_edge_tag") = py::none(),
      py::arg("end_edge_tag") = py::none(), py::arg("seam_edge_tag") = py::none(),
      "Create a cylinder with native kernel-backed Face and Edge topology tags.\n\n"
      "The cylinder extends ``height`` along ``axis`` from the bottom face.\n\n"
      "Args:\n"
      "    radius: Cylinder radius.\n"
      "    height: Cylinder length along ``axis``.\n"
      "    bottom_face_center: Geometric center of the cylinder's bottom\n"
      "        (start) face in the current coordinate system; the solid extends\n"
      "        the full ``height`` along ``axis`` from this point.\n"
      "    axis: Direction of the cylinder axis in the current coordinate\n"
      "        system.");
  m.def(
      "make_cone_rsolid",
      [axial_tags](const Scalar& bottom_radius, const Scalar& height, const Scalar& top_radius, const Scalar3& center,
                   const Scalar3& axis, OptionalString tag_prefix, OptionalString result_tag, OptionalString start_face,
                   OptionalString end_face, OptionalString side_face, OptionalString start_edge,
                   OptionalString end_edge, OptionalString seam_edge) {
        return make_cone_rsolid(
            bottom_radius, height, top_radius, center, axis,
            axial_tags(std::move(tag_prefix), std::move(result_tag), std::move(start_face), std::move(end_face),
                       std::move(side_face), std::move(start_edge), std::move(end_edge), std::move(seam_edge)));
      },
      py::arg("bottom_radius"), py::arg("height"), py::arg("top_radius") = 0.0,
      py::arg("bottom_face_center") = origin(), py::arg("axis") = unit_z(), py::kw_only(),
      py::arg("tag_prefix") = py::none(), py::arg("result_tag") = py::none(), py::arg("start_face_tag") = py::none(),
      py::arg("end_face_tag") = py::none(), py::arg("side_face_tag") = py::none(),
      py::arg("start_edge_tag") = py::none(), py::arg("end_edge_tag") = py::none(),
      py::arg("seam_edge_tag") = py::none(),
      "Create a cone or frustum with native kernel-backed topology tags.\n\n"
      "The solid extends ``height`` along ``axis`` from the bottom face,\n"
      "tapering from ``bottom_radius`` to ``top_radius`` (a cone when\n"
      "``top_radius`` is 0).\n\n"
      "Args:\n"
      "    bottom_radius: Radius of the bottom (start) face.\n"
      "    height: Frustum length along ``axis``.\n"
      "    top_radius: Radius of the top face; 0 produces a cone.\n"
      "    bottom_face_center: Geometric center of the bottom (start) face in\n"
      "        the current coordinate system; the solid extends the full\n"
      "        ``height`` along ``axis`` from this point.\n"
      "    axis: Direction of the frustum axis in the current coordinate\n"
      "        system.");
  m.def("make_sphere_rsolid", &make_sphere_rsolid, py::arg("radius"), py::arg("center") = origin(),
        "Create a sphere solid.");
}

void bind_brep_region(py::module_& m) {
  m.def(
      "load_brep_region_rsolid",
      [](const py::object& path, const std::string& sha256, const OptionalString& tag_prefix) {
        return load_brep_region_rsolid(path_text(path), sha256, tag_prefix);
      },
      py::arg("path"), py::arg("sha256"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Load a hash-pinned, target-derived BREP region snapshot as one Solid.\n\n"
      "The complete artifact SHA-256 is verified before native BREP decoding. In a\n"
      "GraphSession, ``path`` must be relative and is replayed relative to the replay\n"
      "process working directory. Model JSON records the locator and digest, not the\n"
      "sidecar bytes.");
  m.def(
      "_brep_region_path",
      [](const py::object& path, bool for_graph) { return scad::io::checked_region_path(path_text(path), for_graph); },
      py::arg("path"), py::kw_only(), py::arg("for_graph"),
      "The checks on a .scadbrep locator (graph replay: relative, no drive, no '..', '/' separators).");
  m.def(
      "load_brep_region_rshell",
      [](const py::object& path, const std::string& sha256, const OptionalString& tag_prefix) {
        return load_brep_region_rshell(path_text(path), sha256, tag_prefix);
      },
      py::arg("path"), py::arg("sha256"), py::kw_only(), py::arg("tag_prefix") = py::none(),
      "Load a hash-pinned, target-derived BREP face region as one Shell.\n\n"
      "The Shell keeps target-derived topology and is tagged with imported-sidecar\n"
      "provenance. Use ordinary replayable surface operations to join it to fitted\n"
      "or analytic feature faces. GraphSession requires a relative sidecar path.");
}

// The names `simplecadapi/__init__.py` exports for these operators.
void bind_aliases(py::module_& m) {
  static constexpr std::pair<const char*, const char*> kAliases[] = {
      {"create_angle_arc", "make_angle_arc_redge"},
      {"create_angle_arc_wire", "make_angle_arc_rwire"},
      {"create_arc", "make_three_point_arc_redge"},
      {"create_arc_wire", "make_three_point_arc_rwire"},
      {"create_box", "make_box_rsolid"},
      {"create_circle_edge", "make_circle_redge"},
      {"create_circle_face", "make_circle_rface"},
      {"create_circle_wire", "make_circle_rwire"},
      {"create_cylinder", "make_cylinder_rsolid"},
      {"create_face_from_wire", "make_face_from_wire_rface"},
      {"create_face_from_wires", "make_face_from_wires_rface"},
      {"create_helix", "make_helix_redge"},
      {"create_helix_wire", "make_helix_rwire"},
      {"create_interpolated_spline", "make_interpolated_spline_redge"},
      {"create_interpolated_spline_wire", "make_interpolated_spline_rwire"},
      {"create_line", "make_line_redge"},
      {"create_periodic_spline_wire", "make_periodic_spline_rwire"},
      {"create_point", "make_point_rvertex"},
      {"create_polyline_wire", "make_polyline_rwire"},
      {"create_rectangle_face", "make_rectangle_rface"},
      {"create_rectangle_wire", "make_rectangle_rwire"},
      {"create_segment", "make_segment_redge"},
      {"create_segment_wire", "make_segment_rwire"},
      {"create_sphere", "make_sphere_rsolid"},
      {"create_spline", "make_spline_redge"},
      {"create_spline_wire", "make_spline_rwire"},
      {"create_wire_from_edges", "make_wire_from_edges_rwire"},
  };
  for (const auto& [alias, name] : kAliases)
    m.attr(alias) = m.attr(name);
}

// Measurements the parity tests compare with the reference SDK (which reads them off OCP).
void bind_testing(py::module_& m) {
  py::module_ t = m.def_submodule("_geometry_testing", "measurements for the geometry parity tests");
  t.def("bbox", [](const Shape& shape) {
    const auto b = shape.bounding_box();
    return std::array<double, 6>{b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax};
  });
  // `count` points along an edge, evenly in parameter, for checking the winding of a curve.
  t.def("sample", [](const Edge& edge, int count) {
    BRepAdaptor_Curve curve(TopoDS::Edge(edge.wrapped()));
    std::vector<std::array<double, 3>> points;
    for (int i = 0; i <= count; ++i) {
      const gp_Pnt p =
          curve.Value(curve.FirstParameter() + (curve.LastParameter() - curve.FirstParameter()) * i / count);
      points.push_back({p.X(), p.Y(), p.Z()});
    }
    return points;
  });
  // Distinct faces / edges / vertices of the shape (TopExp::MapShapes).
  t.def("counts", [](const Shape& shape) {
    const auto count = [&](TopAbs_ShapeEnum kind) {
      TopTools_IndexedMapOfShape map;
      TopExp::MapShapes(shape.wrapped(), kind, map);
      return map.Extent();
    };
    return py::dict("faces"_a = count(TopAbs_FACE), "edges"_a = count(TopAbs_EDGE),
                    "vertices"_a = count(TopAbs_VERTEX));
  });
}

}  // namespace

void bind_ops_geometry(py::module_& m) {
  bind_lines(m);
  bind_circles(m);
  bind_rectangles(m);
  bind_arcs(m);
  bind_splines(m);
  bind_helix(m);
  bind_wires_and_faces(m);
  bind_primitives(m);
  bind_brep_region(m);
  bind_aliases(m);
  bind_testing(m);
  scad::register_geometry_executors(scad::reactive::ExecutorRegistry::global());
}
