// Rigid transforms on raw OCCT shapes (ocp_transforms.py, translate_shape of
// ocp_features.py).  Wrapping the result in a typed handle is the caller's job.
#pragma once

#include <gp_Trsf.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

// ---- the transformations themselves ---------------------------------------
gp_Trsf translation_trsf(const Vec3& vector);
// Counter-clockwise by `angle_degrees` about the line through `origin` along `axis`.
gp_Trsf rotation_trsf(double angle_degrees, const Vec3& axis, const Vec3& origin);
// Reflection through the plane through `plane_origin` with normal `plane_normal`.
gp_Trsf mirror_trsf(const Vec3& plane_origin, const Vec3& plane_normal);
// Local -> global for the frame (origin, x, y, z); the axes are the columns.
gp_Trsf placement_trsf(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis);

// ---- applying them ---------------------------------------------------------
// `copy` duplicates the geometry (BRepBuilderAPI_Transform's flag).  The Python
// SDK always copies, so the result never shares a TShape with the input and a
// boolean on either cannot touch the other's tolerances.  (OCCT copies anyway
// for a mirror or any transform that is not a pure rotation/translation.)
TopoDS_Shape apply_transform(const TopoDS_Shape& shape, const gp_Trsf& trsf, bool copy = true);

TopoDS_Shape translate_shape(const TopoDS_Shape& shape, const Vec3& vector);
TopoDS_Shape rotate_shape(const TopoDS_Shape& shape, double angle_degrees, const Vec3& axis, const Vec3& origin);
TopoDS_Shape mirror_shape(const TopoDS_Shape& shape, const Vec3& plane_origin, const Vec3& plane_normal);
TopoDS_Shape place_shape(const TopoDS_Shape& shape, const Vec3& origin, const Vec3& x_axis,
                         const Vec3& y_axis, const Vec3& z_axis);

}  // namespace scad::kernel
