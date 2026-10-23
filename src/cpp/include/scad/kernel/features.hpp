// OCCT feature builders: faces from wires, loft, sweep, helical sweep
// (ocp_features.py).
#pragma once

#include <optional>
#include <vector>

#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

// A planar face bounded by `wire` (ValueError when the wire is not planar/closed).
TopoDS_Face make_face_from_wire(const TopoDS_Wire& wire);
// The same with holes.  Each inner wire is reversed first so the holes wind opposite the outer wire.
TopoDS_Face make_face_from_wires(const TopoDS_Wire& outer_wire, const std::vector<TopoDS_Wire>& inner_wires);

// Loft a solid through `sections`, each a wire or a vertex (TypeError otherwise);
// ValueError for fewer than two.
// The result is whatever BRepOffsetAPI_ThruSections built (a solid).
TopoDS_Shape make_loft_solid(const std::vector<TopoDS_Shape>& sections, bool ruled = false);

// Sweep `profile_wire` along `path_wire`; `is_frenet` selects the Frenet trihedron.
TopoDS_Shape make_sweep_solid(const TopoDS_Wire& profile_wire, const TopoDS_Wire& path_wire,
                              bool is_frenet = false);

// Sweep a profile along a helix (Frenet mode).  The profile is placed at
// `radius` along `x_direction` (default +X) first; it is expected to be centred on the axis.
TopoDS_Shape make_helical_sweep_solid(const TopoDS_Wire& profile_wire, double pitch, double height,
                                      double radius, const Vec3& center, const Vec3& direction,
                                      const std::optional<Vec3>& x_direction = std::nullopt);

}  // namespace scad::kernel
