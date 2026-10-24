// Measurements on raw OCCT shapes.
#pragma once

#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"

namespace scad::kernel {

struct BoundingBox {
  double xmin = 0, ymin = 0, zmin = 0, xmax = 0, ymax = 0, zmax = 0;
  double xlen() const { return xmax - xmin; }
  double ylen() const { return ymax - ymin; }
  double zlen() const { return zmax - zmin; }
  Vec3 center() const { return {(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2}; }
};

double linear_length(const TopoDS_Shape& edge_or_wire);
double surface_area(const TopoDS_Shape& face_or_shell);
// Knot-span integration (VolumePropertiesGK): exact on NURBS, like the Python SDK.
double volume(const TopoDS_Shape& solid);
// A quick volume with a relative accuracy of about 1e-5 (Gauss-Kronrod, loose tolerance): for
// comparisons that only need the answer when it is not close to a threshold.  `volume` stays the
// precise one.
double volume_estimate(const TopoDS_Shape& shape);

// Centre of mass using the routine that matches the shape's own dimension.
Vec3 center_of_mass(const TopoDS_Shape& shape);

BoundingBox bounding_box(const TopoDS_Shape& shape);
double distance(const TopoDS_Shape& a, const TopoDS_Shape& b);

// Outward face normal at fractional (u, v) of the face's parameter box.
Vec3 face_normal_at(const TopoDS_Face& face, double u = 0.5, double v = 0.5);

}  // namespace scad::kernel
