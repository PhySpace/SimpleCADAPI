#include "scad/ops/geometry/lines.hpp"

#include <BRepBuilderAPI_MakeVertex.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Vertex.hxx>

#include "internal.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/ops/geometry/wires.hpp"

namespace scad {

using namespace geometry_detail;

Vertex make_point_rvertex(const Scalar& x, const Scalar& y, const Scalar& z) {
  static constexpr const char* kOp = "make_point_rvertex";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create a point vertex.",
                               {"One or more coordinate values are not valid finite scalars.",
                                "The current coordinate system rejected the transformed point."},
                               {"Pass numeric x, y, and z values or valid scalar expressions.",
                                "Inspect the coordinate values and the active workplane before retrying."}};
  return guarded(kSpec, [&] {
    const Vec3 point = current_cs().transform_point({evaluate_scalar(x, "x"), evaluate_scalar(y, "y"), evaluate_scalar(z, "z")});
    Vertex vertex(occt_guard([&] { return BRepBuilderAPI_MakeVertex(kernel::to_pnt(point)).Vertex(); }));
    return finalize_primitive_with(std::move(vertex), kOp, [&] {
      return OpParams(kOp, primitive_labels("vertex")).scalar("x", x).scalar("y", y).scalar("z", z).take();
    });
  });
}

namespace {

constexpr const char* kLineOp = "make_line_redge";

const ErrorSpec& line_spec() {
  static const ErrorSpec spec{kLineOp,
                              "Failed to create a line edge.",
                              {"The start or end point is not a valid finite 3D point.",
                               "The transformed points are degenerate or rejected by the kernel."},
                              {"Pass start and end as 3-element numeric tuples or valid expressions.",
                               "Ensure the two points are distinct and finite."}};
  return spec;
}

TopoDS_Edge line_geometry(const Scalar3& start, const Scalar3& end) {
  return guarded(line_spec(), [&] {
    const Vec3 a = place_point(start, "start");
    const Vec3 b = place_point(end, "end");
    return kernel::make_line_edge(a, b);
  });
}

}  // namespace

Edge make_line_redge(const Scalar3& start, const Scalar3& end, const OptionalString& tag_prefix) {
  return guarded(line_spec(), [&] {
    Edge edge = finalize_primitive_with(Edge(line_geometry(start, end)), kLineOp, [&] {
      return OpParams(kLineOp, primitive_labels("edge")).point("start", start).point("end", end).take();
    });
    return with_shape_prefix(std::move(edge), tag_prefix, kLineOp);
  });
}

Edge make_segment_redge(const Scalar3& start, const Scalar3& end) { return make_line_redge(start, end); }

Wire make_segment_rwire(const Scalar3& start, const Scalar3& end) {
  static constexpr const char* kOp = "make_segment_rwire";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create a single-segment wire.",
                               {"The segment endpoints are invalid.", "The kernel could not assemble the segment into a wire."},
                               {"Pass two valid 3D endpoints.",
                                "If the segment is computed dynamically, log the two endpoints before retrying."}};
  return guarded(kSpec, [&] {
    if (graph_recording()) return make_wire_from_edges_rwire({make_line_redge(start, end)});
    const TopoDS_Wire wire = kernel::make_wire_from_edges({line_geometry(start, end)});
    return finalize_primitive_with(Wire(wire), "make_segment_wire", [&] {
      return OpParams("make_segment_wire", primitive_labels("wire")).point("start", start).point("end", end).take();
    });
  });
}

Wire make_polyline_rwire(const std::vector<Scalar3>& points, bool closed) {
  static constexpr const char* kOp = "make_polyline_rwire";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create a polyline wire.",
                               {"Fewer than two points were provided.", "One or more points are invalid or non-finite.",
                                "The kernel rejected the resulting polyline geometry."},
                               {"Pass at least two finite 3D points.",
                                "If closed=True, ensure the sequence describes a valid loop.",
                                "Inspect the evaluated points before retrying."}};
  return guarded(kSpec, [&] {
    if (points.size() < 2) throw ValueError("At least 2 points are required");

    if (graph_recording()) {
      std::vector<Edge> edges;
      edges.reserve(points.size());
      for (std::size_t i = 0; i + 1 < points.size(); ++i) edges.push_back(make_line_redge(points[i], points[i + 1]));
      if (closed && points.size() > 2) edges.push_back(make_line_redge(points.back(), points.front()));
      return make_wire_from_edges_rwire(edges);
    }

    std::vector<Vec3> placed;
    placed.reserve(points.size());
    for (const Scalar3& point : points) placed.push_back(place_point(point, "points"));
    return finalize_primitive_with(Wire(kernel::make_polyline_wire(placed, closed)), "make_polyline_wire", [&] {
      return OpParams("make_polyline_wire", primitive_labels("wire")).points("points", points).boolean("closed", closed).take();
    });
  });
}

}  // namespace scad
