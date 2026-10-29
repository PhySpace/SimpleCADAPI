#include "convert.hpp"

#include <algorithm>
#include <cmath>

#include <TopoDS.hxx>
#include <gp_Ax2.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/topology.hpp"

namespace scad::sketch_detail {

namespace {

constexpr double kPointEps = 1e-9;

// OCCT's canonical in-plane X axis for a normal (what make_circle_redge uses).
Vec3 default_plane_x_direction(const Vec3& normal) {
  const gp_Ax2 axis(gp_Pnt(0.0, 0.0, 0.0), kernel::to_dir(normal, "sketch plane normal"));
  return kernel::from_dir(axis.XDirection());
}

ProfileWire single_edge_wire(const std::string& entity_id, const TopoDS_Edge& edge) {
  const TopoDS_Wire wire_shape = kernel::make_wire_from_edges({edge});
  ProfileWire out{Wire(wire_shape), {}};
  // Remember the wire's own edge: that is the occurrence promotion matches against.
  for (const TopoDS_Edge& wire_edge : kernel::edges_of(wire_shape))
    out.entity_edges.emplace_back(entity_id, wire_edge);
  return out;
}

TopoDS_Edge arc_edge(const Sketch& sketch, const SketchSolveResult& result, const SketchEntity& entity) {
  const std::string& eid = entity.id;
  const SketchPoint2 sp = result.solved_points.at(entity.point_id("start"));
  const SketchPoint2 ep = result.solved_points.at(entity.point_id("end"));
  const SketchPoint2 cp = result.solved_points.at(entity.point_id("center"));
  const double start_radius = std::hypot(sp.first - cp.first, sp.second - cp.second);
  const double end_radius = std::hypot(ep.first - cp.first, ep.second - cp.second);
  const double radius_tolerance = std::max(kPointEps, start_radius * 1.0e-7);
  if (start_radius <= kPointEps)
    throw ValueError("Sketch arc '" + eid + "' has zero radius");
  if (std::abs(start_radius - end_radius) > radius_tolerance) {
    throw ValueError("Sketch arc '" + eid + "' endpoints are not equidistant from its center");
  }
  const double start_angle = std::atan2(sp.second - cp.second, sp.first - cp.first);
  const double end_angle = std::atan2(ep.second - cp.second, ep.first - cp.first);
  double sweep = std::fmod(end_angle - start_angle, 2.0 * kPi);
  if (sweep < 0.0)
    sweep += 2.0 * kPi;  // Python's `% (2 pi)` is non-negative
  if (sweep <= 1.0e-12)
    throw ValueError("Sketch arc '" + eid + "' has a zero sweep");
  const double middle_angle = start_angle + 0.5 * sweep;
  const Vec3 middle = sketch.point3(
      {cp.first + start_radius * std::cos(middle_angle), cp.second + start_radius * std::sin(middle_angle)});
  return kernel::make_arc_three_point_edge(sketch.point3(sp), middle, sketch.point3(ep));
}

TopoDS_Edge bspline_edge(const Sketch& sketch, const SketchSolveResult& result, const SketchEntity& entity) {
  const Value& solved = result.solved_entities.at(entity.id);
  kernel::BSplineSpec spec;
  for (const Value& pole : solved.find("control_points")->as_array()) {
    const auto& xy = pole.as_array();
    spec.control_points.push_back(sketch.point3({xy.at(0).as_double(), xy.at(1).as_double()}));
  }
  const SketchBSpline definition = entity.bspline();
  spec.degree = definition.degree;
  spec.knots = definition.knots;
  spec.multiplicities = definition.multiplicities;
  if (definition.weights)
    spec.weights = *definition.weights;
  spec.periodic = definition.periodic;
  return kernel::make_bspline_edge(spec);
}

ProfileWire edge_entities_wire(const Sketch& sketch, const SketchProfile& profile) {
  const SketchSolveResult& result = *profile.solve;
  std::vector<TopoDS_Edge> edges;
  std::vector<std::string> entity_ids;
  for (std::size_t i = 0; i < profile.entity_ids.size(); ++i) {
    const SketchEntity& entity = sketch.entities().at(profile.entity_ids[i]);
    TopoDS_Edge edge;
    if (entity.kind == kLineKind) {
      edge = kernel::make_line_edge(sketch.point3(result.solved_points.at(entity.point_id("start"))),
                                    sketch.point3(result.solved_points.at(entity.point_id("end"))));
    } else if (entity.kind == kArcKind) {
      edge = arc_edge(sketch, result, entity);
    } else if (entity.kind == kBSplineKind) {
      edge = bspline_edge(sketch, result, entity);
    } else {
      throw ValueError("Unsupported edge kind '" + entity.kind + "' in edge path profile");
    }
    if (profile.reversed[i])
      edge = TopoDS::Edge(edge.Reversed());
    edges.push_back(edge);
    entity_ids.push_back(entity.id);
  }
  const TopoDS_Wire wire_shape = kernel::make_wire_from_edges(edges);
  const std::vector<TopoDS_Edge> wire_edges = kernel::edges_of(wire_shape);
  if (wire_edges.size() != entity_ids.size()) {
    throw ValueError("Sketch profile wire edge count changed during kernel construction");
  }
  ProfileWire out{Wire(wire_shape), {}};
  for (std::size_t i = 0; i < entity_ids.size(); ++i)
    out.entity_edges.emplace_back(entity_ids[i], wire_edges[i]);
  return out;
}

}  // namespace

ProfileWire wire_from_profile(const Sketch& sketch, const SketchProfile& profile) {
  if (profile.kind == "circle") {
    const TopoDS_Edge edge = kernel::make_circle_edge(profile.center, profile.radius, profile.normal,
                                                      default_plane_x_direction(profile.normal));
    return single_edge_wire(profile.entity_ids.at(0), edge);
  }
  if (profile.kind == "ellipse") {
    if (profile.major_radius <= 0.0 || profile.minor_radius <= 0.0) {
      throw ValueError("Ellipse radii must be positive");
    }
    if (profile.minor_radius > profile.major_radius) {
      throw ValueError("Ellipse minor radius must not exceed the major radius");
    }
    const TopoDS_Edge edge = kernel::make_ellipse_edge(profile.center, profile.major_radius, profile.minor_radius,
                                                       profile.normal, profile.major_direction);
    return single_edge_wire(profile.entity_ids.at(0), edge);
  }
  if (profile.kind == "edge_loop" || profile.kind == "edge_chain")
    return edge_entities_wire(sketch, profile);
  throw ValueError("Unsupported sketch profile kind '" + profile.kind + "'");
}

}  // namespace scad::sketch_detail
