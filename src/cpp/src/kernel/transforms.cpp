#include "scad/kernel/transforms.hpp"

#include <BRepBuilderAPI_Transform.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Vec.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::kernel {

gp_Trsf translation_trsf(const Vec3& vector) {
  return occt_guard([&] {
    gp_Trsf trsf;
    trsf.SetTranslation(to_vec(vector));
    return trsf;
  });
}

gp_Trsf rotation_trsf(double angle_degrees, const Vec3& axis, const Vec3& origin) {
  return occt_guard([&] {
    gp_Trsf trsf;
    trsf.SetRotation(gp_Ax1(to_pnt(origin), to_dir(axis, "rotation axis")), angle_degrees * kPi / 180.0);
    return trsf;
  });
}

gp_Trsf mirror_trsf(const Vec3& plane_origin, const Vec3& plane_normal) {
  return occt_guard([&] {
    gp_Trsf trsf;
    trsf.SetMirror(gp_Ax2(to_pnt(plane_origin), to_dir(plane_normal, "mirror plane normal")));
    return trsf;
  });
}

gp_Trsf placement_trsf(const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis, const Vec3& z_axis) {
  return occt_guard([&] {
    gp_Trsf trsf;
    trsf.SetValues(x_axis.x, y_axis.x, z_axis.x, origin.x,  //
                   x_axis.y, y_axis.y, z_axis.y, origin.y,  //
                   x_axis.z, y_axis.z, z_axis.z, origin.z);
    return trsf;
  });
}

TopoDS_Shape apply_transform(const TopoDS_Shape& shape, const gp_Trsf& trsf, bool copy) {
  return occt_guard([&] {
    BRepBuilderAPI_Transform xform(shape, trsf, copy);
    xform.Build();
    if (!xform.IsDone())
      throw ValueError("OCP transform build failed");
    return xform.Shape();
  });
}

TopoDS_Shape translate_shape(const TopoDS_Shape& shape, const Vec3& vector) {
  return apply_transform(shape, translation_trsf(vector));
}

TopoDS_Shape rotate_shape(const TopoDS_Shape& shape, double angle_degrees, const Vec3& axis, const Vec3& origin) {
  return apply_transform(shape, rotation_trsf(angle_degrees, axis, origin));
}

TopoDS_Shape mirror_shape(const TopoDS_Shape& shape, const Vec3& plane_origin, const Vec3& plane_normal) {
  return apply_transform(shape, mirror_trsf(plane_origin, plane_normal));
}

TopoDS_Shape place_shape(const TopoDS_Shape& shape, const Vec3& origin, const Vec3& x_axis, const Vec3& y_axis,
                         const Vec3& z_axis) {
  return apply_transform(shape, placement_trsf(origin, x_axis, y_axis, z_axis));
}

}  // namespace scad::kernel
