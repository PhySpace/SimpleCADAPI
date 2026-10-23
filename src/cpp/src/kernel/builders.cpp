#include "scad/kernel/builders.hpp"

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <gp_Ax2.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::kernel {

namespace {

gp_Ax2 axis2(const Vec3& origin, const Vec3& direction) {
  return gp_Ax2(to_pnt(origin), to_dir(direction, "axis"));
}

gp_Ax2 axis2(const Vec3& origin, const Vec3& direction, const Vec3& x_direction) {
  return gp_Ax2(to_pnt(origin), to_dir(direction, "axis"), to_dir(x_direction, "x axis"));
}

BRepPrimAPI_MakeBox start_box(const Vec3& corner, double dx, double dy, double dz,
                              const std::optional<Axes3>& axes) {
  return axes ? BRepPrimAPI_MakeBox(axis2(corner, axes->z, axes->x), dx, dy, dz)
              : BRepPrimAPI_MakeBox(to_pnt(corner), dx, dy, dz);
}

void require_done(const BRepBuilderAPI_MakeShape& builder, const char* what) {
  if (!builder.IsDone()) throw ValueError(what);
}

}  // namespace

PrimitiveBuild build_box_primitive(const Vec3& corner, double dx, double dy, double dz,
                                   const std::optional<Axes3>& axes) {
  return occt_guard([&] {
    BRepPrimAPI_MakeBox builder = start_box(corner, dx, dy, dz, axes);
    builder.Build();
    require_done(builder, "OCP box builder failed");
    return PrimitiveBuild{
        builder.Solid(),
        {
            {"box.bottom", builder.BottomFace(), "Box.BottomFace"},
            {"box.top", builder.TopFace(), "Box.TopFace"},
            {"box.front", builder.FrontFace(), "Box.FrontFace"},
            {"box.back", builder.BackFace(), "Box.BackFace"},
            {"box.left", builder.LeftFace(), "Box.LeftFace"},
            {"box.right", builder.RightFace(), "Box.RightFace"},
        }};
  });
}

PrimitiveBuild build_cylinder_primitive(const Vec3& origin, const Vec3& axis, double radius, double height) {
  return occt_guard([&] {
    BRepPrimAPI_MakeCylinder builder(axis2(origin, axis), radius, height);
    builder.Build();
    require_done(builder, "OCP cylinder builder failed");
    BRepPrim_Cylinder& primitive = builder.Cylinder();
    return PrimitiveBuild{
        builder.Solid(),
        {
            {"cylinder.start", primitive.BottomFace(), "Cylinder.BottomFace"},
            {"cylinder.end", primitive.TopFace(), "Cylinder.TopFace"},
            {"cylinder.side", primitive.LateralFace(), "Cylinder.LateralFace"},
            {"cylinder.start_boundary", primitive.BottomEdge(), "Cylinder.BottomEdge"},
            {"cylinder.end_boundary", primitive.TopEdge(), "Cylinder.TopEdge"},
            {"cylinder.seam", primitive.StartEdge(), "Cylinder.StartEdge"},
        }};
  });
}

PrimitiveBuild build_cone_primitive(const Vec3& origin, const Vec3& axis, double bottom_radius,
                                    double top_radius, double height) {
  return occt_guard([&] {
    BRepPrimAPI_MakeCone builder(axis2(origin, axis), bottom_radius, top_radius, height);
    builder.Build();
    require_done(builder, "OCP cone builder failed");
    BRepPrim_Cone& primitive = builder.Cone();
    PrimitiveBuild out{builder.Solid(), {}};
    out.roles.reserve(6);
    out.roles.push_back({"cone.start", primitive.BottomFace(), "Cone.BottomFace"});
    // A cone that ends in a point has no top face.
    if (top_radius > 0.0) out.roles.push_back({"cone.end", primitive.TopFace(), "Cone.TopFace"});
    out.roles.push_back({"cone.side", primitive.LateralFace(), "Cone.LateralFace"});
    out.roles.push_back({"cone.start_boundary", primitive.BottomEdge(), "Cone.BottomEdge"});
    out.roles.push_back({"cone.end_boundary", primitive.TopEdge(), "Cone.TopEdge"});
    out.roles.push_back({"cone.seam", primitive.StartEdge(), "Cone.StartEdge"});
    return out;
  });
}

TopoDS_Solid make_box_solid(const Vec3& corner, double dx, double dy, double dz) {
  return occt_guard([&] {
    BRepPrimAPI_MakeBox builder = start_box(corner, dx, dy, dz, std::nullopt);
    builder.Build();
    require_done(builder, "OCP box builder failed");
    return builder.Solid();
  });
}

TopoDS_Solid make_cylinder_solid(const Vec3& origin, const Vec3& axis, double radius, double height) {
  return occt_guard([&] {
    BRepPrimAPI_MakeCylinder builder(axis2(origin, axis), radius, height);
    builder.Build();
    require_done(builder, "OCP cylinder builder failed");
    return builder.Solid();
  });
}

TopoDS_Solid make_cone_solid(const Vec3& origin, const Vec3& axis, double bottom_radius, double top_radius,
                             double height) {
  return occt_guard([&] {
    BRepPrimAPI_MakeCone builder(axis2(origin, axis), bottom_radius, top_radius, height);
    builder.Build();
    require_done(builder, "OCP cone builder failed");
    return builder.Solid();
  });
}

TopoDS_Solid make_sphere_solid(const Vec3& center, double radius) {
  return occt_guard([&] {
    BRepPrimAPI_MakeSphere builder(to_pnt(center), radius);
    builder.Build();
    require_done(builder, "OCP sphere builder failed");
    return builder.Solid();
  });
}

}  // namespace scad::kernel
