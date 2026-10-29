// OCCT primitive builders (ocp_builders.py).
//
// `build_*_primitive` also returns the sub-shapes the kernel itself names
// ("the bottom face of this box"): operation-native role evidence that tracking
// turns into delta roles.  `make_*_solid` are the same builds without the
// witnesses, for callers that only need the solid.
#pragma once

#include <optional>
#include <string_view>
#include <vector>

#include <TopoDS_Shape.hxx>
#include <TopoDS_Solid.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

// A frame as three axes (CoordinateSystem x, y, z).  Only x and z place a
// primitive (gp_Ax2 derives y = z cross x); y rides along so a caller can pass
// a whole CoordinateSystem.
struct Axes3 {
  Vec3 x{1, 0, 0};
  Vec3 y{0, 1, 0};
  Vec3 z{0, 0, 1};
};

struct PrimitiveRoleWitness {
  std::string_view role;             // "box.bottom"
  TopoDS_Shape shape;                // the sub-shape of the solid that plays it
  std::string_view evidence_method;  // "Box.BottomFace"
};

struct PrimitiveBuild {
  TopoDS_Solid solid;
  std::vector<PrimitiveRoleWitness> roles;
};

// A box of size dx*dy*dz with its minimum corner at `corner`; with `axes` the
// box is built in that frame (corner is then its origin in global coordinates).
PrimitiveBuild build_box_primitive(const Vec3& corner, double dx, double dy, double dz,
                                   const std::optional<Axes3>& axes = std::nullopt);
// Axis-aligned/oriented cylinder: base circle centre `origin`, direction `axis`.
PrimitiveBuild build_cylinder_primitive(const Vec3& origin, const Vec3& axis, double radius, double height);
// Cone frustum; `top_radius == 0` gives a point (no top face, hence no "cone.end" role).
PrimitiveBuild build_cone_primitive(const Vec3& origin, const Vec3& axis, double bottom_radius, double top_radius,
                                    double height);

TopoDS_Solid make_box_solid(const Vec3& corner, double dx, double dy, double dz);
TopoDS_Solid make_cylinder_solid(const Vec3& origin, const Vec3& axis, double radius, double height);
TopoDS_Solid make_cone_solid(const Vec3& origin, const Vec3& axis, double bottom_radius, double top_radius,
                             double height);
TopoDS_Solid make_sphere_solid(const Vec3& center, double radius);

}  // namespace scad::kernel
