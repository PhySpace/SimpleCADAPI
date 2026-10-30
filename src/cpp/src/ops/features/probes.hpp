// Geometric probes behind the failure diagnoses (operators/_diagnostics.py).
//
// Each answers one measurable question about raw OCCT shapes -- how far apart, how
// much room, how tangent -- and answers "unknown" (nullopt / false) rather than
// throwing: a diagnosis must never replace the error it explains.  Private to
// src/ops/features.
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Solid.hxx>

#include "scad/core/vec.hpp"

namespace scad::features_detail {

// "(1.5, 0, -2)": each coordinate as Python's {:.4g}.
std::string vector_display(const Vec3& vector);

struct ClosestApproach {
  double gap = 0.0;
  Vec3 point_a, point_b;
};
std::optional<ClosestApproach> closest_approach(const TopoDS_Shape& a, const TopoDS_Shape& b);

// The two end points of an edge in explorer order; nullopt for a degenerate edge.
std::optional<std::pair<Vec3, Vec3>> edge_endpoints(const TopoDS_Shape& edge);

// Uniform parameter samples of an edge: a straight line is just its two ends.
std::vector<Vec3> sample_edge_polyline(const TopoDS_Edge& edge, int samples = 16);

// Which faces of a solid each edge borders.
class EdgeFaceAdjacency {
 public:
  explicit EdgeFaceAdjacency(const TopoDS_Shape& solid);
  // The faces bordering `edge` (IsSame lookup), or nullptr when the solid does not have it.
  const std::vector<TopoDS_Face>* faces_of(const TopoDS_Shape& edge) const;

 private:
  TopTools_IndexedDataMapOfShapeListOfShape map_;
  std::vector<std::vector<TopoDS_Face>> faces_;
};

// Distance from `edge` to the nearest boundary edge of `face` that does not touch it:
// the room a blend has on that face.
std::optional<double> face_extent_from_edge(const TopoDS_Shape& face, const TopoDS_Shape& edge);

// Interior angle between two faces along their shared edge, in degrees; 180 is a tangent
// (smooth) junction.  A concave edge reads as its supplement.
std::optional<double> dihedral_angle_along_edge(const TopoDS_Face& a, const TopoDS_Face& b, const TopoDS_Edge& edge);

// Convexity by probing from the edge midpoint along the outward-normal bisector (inside the
// solid: concave).  nullopt when undeterminable.
std::optional<bool> edge_is_concave(const TopoDS_Solid& solid, const TopoDS_Face& a, const TopoDS_Face& b,
                                    const TopoDS_Edge& edge);

// Convexity by probing along n_a - n_b: unlike the bisector probe it tells a 90 degree convex
// edge from its 270 degree concave supplement.
std::optional<bool> edge_is_concave_side_probe(const TopoDS_Solid& solid, const TopoDS_Face& a, const TopoDS_Face& b,
                                               const TopoDS_Edge& edge);

// True when two edges meet at a vertex with aligned (or anti-aligned) tangents: one smooth curve
// that the kernel split in two.
bool edges_tangent_at_shared_vertex(const TopoDS_Edge& a, const TopoDS_Edge& b);

}  // namespace scad::features_detail
