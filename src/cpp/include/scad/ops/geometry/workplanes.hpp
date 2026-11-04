// Workplanes made from the model: recorded operations whose result is a Workplane value.
//
// A Workplane (scad/core/coordinate_system.hpp) is a frame in world coordinates and the context manager that
// makes it the current system.  These operators build one from geometry -- a planar face, three points, an
// axis, two parallel faces, a curve -- and record the operation with its inputs as ordered `input_refs`, so a
// replay of the graph builds the frame again from the geometry as it is then (a sketch on a face's workplane
// follows the face).  The result takes the lineage of the recorded node, like a Sketch or a Part.
//
// Points and directions given as numbers are read in the current coordinate system, like every operator's;
// geometry inputs are world-space already.  The parameter `frame` of each record holds the frame that was made
// (world coordinates): what a reader that cannot rebuild the inputs falls back to.
#pragma once

#include <optional>
#include <string>
#include <variant>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/scalar.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A point given as numbers (current system) or as a vertex of the model.
using PointOrVertex = std::variant<Scalar3, Vertex>;
// A curve: one edge or a wire.
using EdgeOrWire = std::variant<Edge, Wire>;

// The recorded spelling of SimpleWorkplane(origin, normal, x_dir): a frame in the current system.
Workplane make_workplane_rworkplane(const Scalar3& origin = scalar3(0, 0, 0), const Scalar3& normal = scalar3(0, 0, 1),
                                    const Scalar3& x_dir = scalar3(1, 0, 0));

// On a planar face: normal = the face's outward normal (`flip` reverses it), origin = the face's centre or
// `origin` projected onto the face's plane, x = along `x_edge` (its direction at its start, projected onto the
// plane), or along `x_dir` (projected), or the x direction of the face's own plane.  `offset` moves the origin
// along the normal.  ValueError for a face that is not planar, both `x_edge` and `x_dir`, or an x direction
// normal to the plane.
Workplane make_workplane_from_face_rworkplane(const Face& face, const std::optional<Scalar3>& origin = std::nullopt,
                                              const std::optional<Edge>& x_edge = std::nullopt,
                                              const std::optional<Scalar3>& x_dir = std::nullopt,
                                              const Scalar& offset = Scalar(0.0), bool flip = false);

// Through three points: origin = a, x towards b, normal = (b - a) x (c - a).  ValueError when they are collinear.
Workplane make_workplane_from_points_rworkplane(const PointOrVertex& a, const PointOrVertex& b, const PointOrVertex& c);

// Through an axis, turned by `angle` (degrees, right-handed about the axis): the axis is a straight edge (from
// its start, along it) or a circular edge (its centre, along the circle's normal).  x = the axis direction.  At
// angle 0 the plane is the plane of `face` (a planar face containing the axis direction, usually one the edge
// bounds), or without one, the plane whose normal is the global Z (or X for an axis along Z) made square to the
// axis.  ValueError for an edge that is neither straight nor circular, or a face whose normal is along the axis.
Workplane make_workplane_from_axis_rworkplane(const Edge& axis, const Scalar& angle = Scalar(0.0),
                                              const std::optional<Face>& face = std::nullopt);

// Halfway between two parallel planar faces: normal and x from `face_a`, origin = the middle between the centre
// of `face_a` and its projection onto the plane of `face_b`.  ValueError when a face is not planar or the faces
// are not parallel.
Workplane make_workplane_midplane_rworkplane(const Face& face_a, const Face& face_b);

// Normal to a curve, for a sweep profile: origin = the point at `at` (a fraction of the curve's length, 0 =
// start, 1 = end), normal = the direction of travel there, x = `x_dir` projected onto the plane, or the global Z
// made square to the normal (the global X when the tangent is near Z; orthonormal_plane_axes).  ValueError for `at`
// outside [0, 1] or an x direction along the tangent.
Workplane make_workplane_normal_to_curve_rworkplane(const EdgeOrWire& curve, const Scalar& at = Scalar(0.0),
                                                    const std::optional<Scalar3>& x_dir = std::nullopt);

// A workplane placed relative to another: moved by `offset` (along the base's own x, y and normal) and turned by
// `rx`, `ry`, `rz` degrees about the base's own axes, in that order (each about the axis as the previous turns left
// it: R = Rx(rx) Ry(ry) Rz(rz) in the base's frame).  The base is a workplane value, recorded as this node's input so
// the new plane follows it, or a named plane (`base_plane` "XY" | "XZ" | "YZ", as sketches read them).  The editor's
// move and turn handles write exactly these numbers.
Workplane make_workplane_offset_rworkplane(const Workplane& base, const Scalar3& offset = scalar3(0, 0, 0),
                                           const Scalar& rx = Scalar(0.0), const Scalar& ry = Scalar(0.0),
                                           const Scalar& rz = Scalar(0.0),
                                           const std::optional<std::string>& base_plane = std::nullopt);

}  // namespace scad
