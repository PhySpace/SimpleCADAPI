// Vec3 <-> OpenCASCADE geometry conversions.
#pragma once

#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

inline gp_Pnt to_pnt(const Vec3& v) { return gp_Pnt(v.x, v.y, v.z); }
inline gp_Vec to_vec(const Vec3& v) { return gp_Vec(v.x, v.y, v.z); }
inline Vec3 from_pnt(const gp_Pnt& p) { return {p.X(), p.Y(), p.Z()}; }
inline Vec3 from_vec(const gp_Vec& v) { return {v.X(), v.Y(), v.Z()}; }
inline Vec3 from_dir(const gp_Dir& d) { return {d.X(), d.Y(), d.Z()}; }

// gp_Dir throws Standard_ConstructionError on a zero vector; this raises a
// scad::ValueError that says which vector.
gp_Dir to_dir(const Vec3& v, const char* what = "direction");

}  // namespace scad::kernel
