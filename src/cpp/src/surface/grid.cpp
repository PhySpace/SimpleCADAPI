#include <algorithm>

#include <BRepBuilderAPI_MakeFace.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS.hxx>

#include "internal.hpp"
#include "scad/core/coordinate_system.hpp"
#include "scad/kernel/topology.hpp"

namespace scad::surface::detail {

double require_positive_finite(double value, std::string_view label) {
  if (!std::isfinite(value) || value <= 0.0)
    throw ValueError(std::string(label) + " must be a positive finite value");
  return value;
}

PointGrid checked_point_grid(const PointGrid& points) {
  if (points.size() < 2 || std::any_of(points.begin(), points.end(), [](const auto& row) { return row.size() < 2; }))
    throw ValueError("surface point grids require at least 2 rows and 2 columns");
  const std::size_t width = points.front().size();
  if (std::any_of(points.begin(), points.end(), [&](const auto& row) { return row.size() != width; }))
    throw ValueError("surface point grids must be rectangular");
  for (const auto& row : points)
    for (const Vec3& point : row)
      if (!point.is_finite()) throw ValueError("surface points must be finite");
  return points;
}

PointGrid to_global(const PointGrid& points) {
  const CoordinateSystem& cs = current_cs();
  PointGrid out;
  out.reserve(points.size());
  for (const auto& row : points) {
    std::vector<Vec3> converted;
    converted.reserve(row.size());
    for (const Vec3& point : row) converted.push_back(cs.transform_point(point));
    out.push_back(std::move(converted));
  }
  return out;
}

std::vector<Vec3> constraint_points_to_global(const std::vector<Vec3>& points) {
  const CoordinateSystem& cs = current_cs();
  std::vector<Vec3> out;
  out.reserve(points.size());
  for (const Vec3& point : points) {
    if (!point.is_finite()) throw ValueError("surface constraint points must be finite 3D points");
    out.push_back(cs.transform_point(point));
  }
  return out;
}

namespace {
Value point_value(const Vec3& p) { return Value(Value::Array{p.x, p.y, p.z}); }
}  // namespace

Value to_value(const std::vector<Vec3>& points) {
  Value::Array out;
  out.reserve(points.size());
  for (const Vec3& p : points) out.push_back(point_value(p));
  return Value(std::move(out));
}

Value to_value(const PointGrid& grid) {
  Value::Array rows;
  rows.reserve(grid.size());
  for (const auto& row : grid) rows.push_back(to_value(row));
  return Value(std::move(rows));
}

Value to_value(const std::optional<WeightGrid>& weights) {
  if (!weights) return {};
  Value::Array rows;
  for (const auto& row : *weights) {
    Value::Array cells;
    for (double w : row) cells.emplace_back(w);
    rows.emplace_back(std::move(cells));
  }
  return Value(std::move(rows));
}

void note_symbolic(SymbolicArgs& out, std::string name, const Scalar& value) {
  if (value.symbolic()) out.emplace_back(std::move(name), value);
}

Value to_value(const TagPrefix& tag_prefix) { return tag_prefix ? Value(*tag_prefix) : Value(); }

TopoDS_Face face_from_surface(const Handle(Geom_Surface)& surface) {
  BRepBuilderAPI_MakeFace builder(surface, Precision::Confusion());
  if (!builder.IsDone()) throw ValueError("OCP could not create a face from the generated surface");
  return builder.Face();
}

TopoDS_Face single_face(const TopoDS_Shape& shape, std::string_view what) {
  if (shape.ShapeType() == TopAbs_FACE) return TopoDS::Face(shape);
  const auto faces = kernel::faces_of(shape);
  if (faces.size() != 1)
    throw ValueError("surface " + std::string(what) + " must create exactly one face, got " +
                     std::to_string(faces.size()));
  return faces.front();
}

}  // namespace scad::surface::detail
