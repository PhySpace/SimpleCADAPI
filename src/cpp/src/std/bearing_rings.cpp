#include "bearing_rings.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

#include "metadata.hpp"
#include "scad/core/error.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/semantic/selection.hpp"

namespace scad::stdlib {

namespace {

Scalar3 at(double radius, double z) {
  return scalar3(radius, 0.0, z);
}

Solid apply_edge_chamfer(const Solid& solid, double edge_chamfer, double bearing_width) {
  if (edge_chamfer <= 0.0)
    return solid;
  const double circular_min_length = std::max(1e-6, bearing_width * 1.1);
  std::vector<Edge> edges;
  for (const Edge& edge : solid.edges()) {
    if (edge.length() > circular_min_length)
      edges.push_back(edge);
  }
  if (edges.empty())
    return solid;
  return chamfer_rsolid(solid, edges, edge_chamfer);
}

}  // namespace

Solid make_race_ring_solid(double bore_or_inner_radius, double outer_or_shoulder_radius, double ball_pitch_radius,
                           double groove_radius, double bearing_width, double edge_chamfer, RingRole role) {
  const double half_width = bearing_width / 2.0;
  const double inner_radius = bore_or_inner_radius;
  const double outer_radius = outer_or_shoulder_radius;
  std::vector<Edge> edges;
  double mouth_z = 0.0;

  if (role == RingRole::Inner) {
    const double mouth_offset = ball_pitch_radius - outer_radius;
    if (mouth_offset <= 0.0 || mouth_offset >= groove_radius) {
      throw ValueError("inner ring shoulder radius must expose the raceway groove");
    }
    mouth_z = std::sqrt(std::max(0.0, groove_radius * groove_radius - mouth_offset * mouth_offset));
    const Scalar3 p0 = at(inner_radius, -half_width), p1 = at(outer_radius, -half_width);
    const Scalar3 arc_start = at(outer_radius, -mouth_z), arc_mid = at(ball_pitch_radius - groove_radius, 0.0);
    const Scalar3 arc_end = at(outer_radius, mouth_z);
    const Scalar3 p5 = at(outer_radius, half_width), p6 = at(inner_radius, half_width);
    edges = {make_line_redge(p0, p1),
             make_line_redge(p1, arc_start),
             make_three_point_arc_redge(arc_start, arc_mid, arc_end),
             make_line_redge(arc_end, p5),
             make_line_redge(p5, p6),
             make_line_redge(p6, p0)};
  } else {
    const double mouth_offset = inner_radius - ball_pitch_radius;
    if (mouth_offset <= 0.0 || mouth_offset >= groove_radius) {
      throw ValueError("outer ring shoulder radius must expose the raceway groove");
    }
    mouth_z = std::sqrt(std::max(0.0, groove_radius * groove_radius - mouth_offset * mouth_offset));
    const Scalar3 p0 = at(inner_radius, -half_width), p1 = at(outer_radius, -half_width);
    const Scalar3 p2 = at(outer_radius, half_width), p3 = at(inner_radius, half_width);
    const Scalar3 arc_start = at(inner_radius, mouth_z), arc_mid = at(ball_pitch_radius + groove_radius, 0.0);
    const Scalar3 arc_end = at(inner_radius, -mouth_z);
    edges = {make_line_redge(p0, p1),
             make_line_redge(p1, p2),
             make_line_redge(p2, p3),
             make_line_redge(p3, arc_start),
             make_three_point_arc_redge(arc_start, arc_mid, arc_end),
             make_line_redge(arc_end, p0)};
  }

  const Face profile = make_face_from_wire_rface(make_wire_from_edges_rwire(edges), scalar3(0.0, -1.0, 0.0));
  Solid ring = revolve_rsolid(profile, scalar3(0.0, 0.0, 1.0), 360.0, scalar3(0.0, 0.0, 0.0));
  const char* role_name = role == RingRole::Inner ? "inner_ring" : "outer_ring";
  ring = Solid(apply_tag(ring, std::string("role.") + role_name));
  ring = Solid(apply_tag(ring, "group.ball_bearing"));
  ring = apply_edge_chamfer(ring, edge_chamfer, bearing_width);
  ring.set_metadata("std.bearing.ring",
                    Dict("role", role_name)("inner_radius", inner_radius)("outer_radius", outer_radius)(
                        "ball_pitch_radius", ball_pitch_radius)("groove_radius", groove_radius)(
                        "raceway_mouth_z", mouth_z)("bearing_width", bearing_width)("edge_chamfer", edge_chamfer)
                        .take());
  return ring;
}

}  // namespace scad::stdlib
