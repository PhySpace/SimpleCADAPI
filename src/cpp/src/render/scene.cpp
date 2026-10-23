#include <cmath>

#include "scad/core/error.hpp"
#include "scad/render/render.hpp"

namespace scad::render {

int Scene::add_mesh(std::shared_ptr<const io::Mesh> mesh, MeshStyle style) {
  if (!mesh) throw ValueError("add_mesh: null mesh");
  if (!(style.opacity >= 0.0f && style.opacity <= 1.0f)) throw ValueError("opacity must be within [0, 1]");
  meshes_.push_back({std::move(mesh), std::move(style)});
  return static_cast<int>(meshes_.size()) - 1;
}

int Scene::add_lines(Polylines lines, LineStyle style) {
  if (lines.starts.empty()) lines.starts.push_back(0);
  if (lines.starts.back() * 3 != lines.points.size()) throw ValueError("add_lines: starts do not match points");
  lines_.push_back({std::move(lines), style});
  return static_cast<int>(lines_.size()) - 1;
}

int Scene::add_points(std::vector<float> xyz, PointStyle style) {
  if (xyz.size() % 3 != 0) throw ValueError("add_points: expected a multiple of three values");
  points_.push_back({std::move(xyz), style});
  return static_cast<int>(points_.size()) - 1;
}

int Scene::add_shape(const TopoDS_Shape& shape, MeshStyle style, const io::MeshParameters& mesh_parameters,
                     bool edges, const LineStyle& edge_style) {
  auto mesh = std::make_shared<io::Mesh>(io::mesh(shape, mesh_parameters));
  const int index = add_mesh(std::move(mesh), std::move(style));
  if (edges) add_lines(edge_polylines(shape, std::min(mesh_parameters.linear_deflection, 0.04)), edge_style);
  return index;
}

Bounds Scene::bounds() const {
  Bounds b;
  for (const auto& m : meshes_) {
    const auto& v = m.mesh->vertices;
    // Only vertices that a triangle uses count, like a VTK dataset's bounds.
    for (std::size_t i = 0; i + 2 < v.size(); i += 3) b.add({v[i], v[i + 1], v[i + 2]});
  }
  for (const auto& l : lines_)
    for (std::size_t i = 0; i + 2 < l.lines.points.size(); i += 3)
      b.add({l.lines.points[i], l.lines.points[i + 1], l.lines.points[i + 2]});
  for (const auto& p : points_)
    for (std::size_t i = 0; i + 2 < p.xyz.size(); i += 3) b.add({p.xyz[i], p.xyz[i + 1], p.xyz[i + 2]});
  return b;
}

std::size_t Scene::triangle_count() const {
  std::size_t n = 0;
  for (const auto& m : meshes_) n += m.mesh->triangle_count();
  return n;
}

}  // namespace scad::render
