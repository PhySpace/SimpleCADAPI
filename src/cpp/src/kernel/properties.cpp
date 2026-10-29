#include "scad/kernel/properties.hpp"

#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepLProp_SLProps.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopoDS.hxx>

#include <cmath>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::kernel {

namespace {

Vec3 centre_of(const GProp_GProps& props) {
  return from_pnt(props.CentreOfMass());
}

// The centre when the reported mass is meaningfully non-zero.
bool mass_point(const GProp_GProps& props, Vec3& out, double eps = 1e-12) {
  if (std::abs(props.Mass()) <= eps)
    return false;
  out = centre_of(props);
  return true;
}

}  // namespace

double linear_length(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    GProp_GProps props;
    BRepGProp::LinearProperties(shape, props);
    return props.Mass();
  });
}

double surface_area(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
  });
}

double volume(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    GProp_GProps props;
    // Knot-span integration: the fixed-order routine loses precision on
    // rational curves and can crash on affine-transformed trims.
    BRepGProp::VolumePropertiesGK(shape, props, 1e-9, true, true);
    return props.Mass();
  });
}

double volume_estimate(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    GProp_GProps props;
    BRepGProp::VolumePropertiesGK(shape, props, 1e-5, true, true);
    return props.Mass();
  });
}

BoundingBox bounding_box(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    Bnd_Box box;
    box.SetGap(0.0);
    BRepBndLib::AddOptimal(shape, box, false, false);
    if (box.IsVoid())
      throw ValueError("shape has no bounding box (empty or null shape)");
    BoundingBox out;
    box.Get(out.xmin, out.ymin, out.zmin, out.xmax, out.ymax, out.zmax);
    return out;
  });
}

Vec3 center_of_mass(const TopoDS_Shape& shape) {
  if (shape.IsNull())
    throw ValueError("center_of_mass of a null shape");
  return occt_guard([&]() -> Vec3 {
    Vec3 point;
    GProp_GProps props;
    switch (shape.ShapeType()) {
      case TopAbs_SOLID:
      case TopAbs_COMPSOLID:
      case TopAbs_COMPOUND:
        try {
          BRepGProp::VolumePropertiesGK(shape, props, 1e-9, true, true);
          if (mass_point(props, point))
            return point;
        } catch (...) {
        }
        if (shape.ShapeType() == TopAbs_COMPOUND) {
          // A compound may hold only faces or edges.
          try {
            GProp_GProps surface;
            BRepGProp::SurfaceProperties(shape, surface);
            if (mass_point(surface, point))
              return point;
          } catch (...) {
          }
          try {
            GProp_GProps linear;
            BRepGProp::LinearProperties(shape, linear);
            if (mass_point(linear, point))
              return point;
          } catch (...) {
          }
        }
        return bounding_box(shape).center();
      case TopAbs_FACE:
      case TopAbs_SHELL:
        try {
          BRepGProp::SurfaceProperties(shape, props);
          if (mass_point(props, point))
            return point;
        } catch (...) {
        }
        return bounding_box(shape).center();
      case TopAbs_WIRE:
      case TopAbs_EDGE:
        try {
          BRepGProp::LinearProperties(shape, props);
          if (mass_point(props, point))
            return point;
        } catch (...) {
        }
        return bounding_box(shape).center();
      case TopAbs_VERTEX:
        return from_pnt(BRep_Tool::Pnt(TopoDS::Vertex(shape)));
      default:
        return bounding_box(shape).center();
    }
  });
}

double distance(const TopoDS_Shape& a, const TopoDS_Shape& b) {
  return occt_guard([&] {
    BRepExtrema_DistShapeShape dist(a, b);
    if (!dist.IsDone())
      throw ValueError("OCCT distance calculation failed");
    return dist.Value();
  });
}

Vec3 face_normal_at(const TopoDS_Face& face, double u, double v) {
  return occt_guard([&]() -> Vec3 {
    BRepAdaptor_Surface adaptor(face, true);
    const double umin = adaptor.FirstUParameter();
    const double umax = adaptor.LastUParameter();
    const double vmin = adaptor.FirstVParameter();
    const double vmax = adaptor.LastVParameter();
    BRepLProp_SLProps props(adaptor, umin + (umax - umin) * u, vmin + (vmax - vmin) * v, 1, 1e-7);
    if (!props.IsNormalDefined())
      throw ValueError("Face normal is not defined at the requested parameters");
    gp_Dir n = props.Normal();
    if (face.Orientation() == TopAbs_REVERSED)
      n.Reverse();
    return from_dir(n);
  });
}

}  // namespace scad::kernel
