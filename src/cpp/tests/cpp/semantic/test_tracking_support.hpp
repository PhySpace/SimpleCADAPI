// Shared fixtures and the delta summariser for the tracking tests.
#pragma once

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <string>
#include <unordered_map>
#include <vector>

#include <TopAbs_ShapeEnum.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"
#include "scad/kernel/builders.hpp"
#include "scad/kernel/curves.hpp"
#include "scad/kernel/features.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/semantic/tracking.hpp"
#include "scad/topo/shape.hpp"

namespace scad::tracking_test {

// ---- fixtures ---------------------------------------------------------------

// make_box_rsolid(w, h, d): centred on the origin in x/y, standing on z = 0.
inline Solid box_solid(double w, double h, double d, const Vec3& bottom_centre = {0, 0, 0}) {
  return Solid(kernel::make_box_solid(bottom_centre - Vec3{w / 2, h / 2, 0}, w, h, d));
}

inline Solid cylinder_solid(double radius, double height, const Vec3& bottom_centre) {
  return Solid(kernel::make_cylinder_solid(bottom_centre, {0, 0, 1}, radius, height));
}

// make_rectangle_rwire(w, h, center=...): in the plane z = centre.z, counter-clockwise.
inline Wire rectangle_wire(double w, double h, const Vec3& centre = {0, 0, 0}) {
  const double x = w / 2, y = h / 2;
  return Wire(kernel::make_polyline_wire({centre + Vec3{-x, -y, 0}, centre + Vec3{x, -y, 0},
                                          centre + Vec3{x, y, 0}, centre + Vec3{-x, y, 0}},
                                         /*closed=*/true));
}

inline Face rectangle_face(double w, double h, const Vec3& centre = {0, 0, 0}) {
  return Face(kernel::make_face_from_wire(TopoDS::Wire(rectangle_wire(w, h, centre).wrapped())));
}

inline Face circle_face(const Vec3& centre, double radius) {
  const TopoDS_Edge edge = kernel::make_circle_edge(centre, radius, {0, 0, 1});
  return Face(kernel::make_face_from_wire(kernel::make_wire_from_edges({edge})));
}

// ---- the summary the reference recorder writes -------------------------------

using ShapeIndex = std::unordered_map<std::string, TopoDS_Shape>;

// Every vertex, edge, face, wire and solid below each root (and the roots), by
// kernel id; the first shape seen under an id wins.
inline ShapeIndex index_shapes(const std::vector<TopoDS_Shape>& roots) {
  ShapeIndex found;
  for (const TopoDS_Shape& root : roots) {
    for (TopAbs_ShapeEnum type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE, TopAbs_SOLID}) {
      for (const TopoDS_Shape& shape : kernel::explore(root, type)) found.emplace(kernel_topo_id(shape), shape);
    }
    found.emplace(kernel_topo_id(root), root);
  }
  return found;
}

inline std::string centre_text(const ShapeIndex& index, const std::string& id) {
  const auto it = index.find(id);
  if (it == index.end()) return "?";
  const Vec3 c = kernel::center_of_mass(it->second);
  char buffer[96];
  std::snprintf(buffer, sizeof buffer, "(%.4f,%.4f,%.4f)", c.x + 0.0, c.y + 0.0, c.z + 0.0);
  std::string text = buffer;
  // -0.0000 is what a tiny negative prints as; the recorder rounds first.
  for (std::size_t at; (at = text.find("-0.0000")) != std::string::npos;) text.erase(at, 1);
  return text;
}

inline std::string upper(std::string_view kind) {
  std::string out(kind);
  std::transform(out.begin(), out.end(), out.begin(), [](unsigned char ch) { return static_cast<char>(std::toupper(ch)); });
  return out;
}

inline std::string join(const Value* list) {
  std::string out;
  if (list == nullptr) return out;
  for (const Value& item : list->as_array()) out += (out.empty() ? "" : ",") + item.as_string();
  return out;
}

// counts first, then the sorted E/R/S/D lines of tracking_golden_record.py.
inline std::vector<std::string> summarise(const TopoDelta& delta, const DeltaEntries& entries,
                                          const std::vector<TopoDS_Shape>& inputs, const TopoDS_Shape& result) {
  std::vector<TopoDS_Shape> roots = inputs;
  roots.push_back(result);
  const ShapeIndex index = index_shapes(roots);

  std::vector<std::string> lines;
  std::vector<std::string> body;
  lines.push_back("counts preserved=" + std::to_string(delta.preserved.size()) +
                  " modified=" + std::to_string(delta.modified.size()) +
                  " generated=" + std::to_string(delta.generated.size()) +
                  " deleted=" + std::to_string(delta.deleted.size()) +
                  " section_edges=" + std::to_string(delta.section_edges.size()) +
                  " entries=" + std::to_string(delta.entries.size()) +
                  " roles=" + std::to_string(delta.roles.size()) +
                  " delta_entries=" + std::to_string(entries.size()));

  for (const TopoEntry& e : delta.entries) {
    const TopoRef& source = e.parent_refs.at(0);
    const Value* result_role = e.metadata.find("result_role");
    const Value* project = e.metadata.find("project_source_tags");
    body.push_back("E " + std::string(to_string(e.event)) + "|" + e.origin_role.value_or("-") + "|" +
                   e.metadata.find("derivation")->as_string() + "|" +
                   (result_role ? result_role->as_string() : std::string("-")) + "|" +
                   (project && project->as_bool() ? "True" : "False") + "|" + upper(kind_name(source.kind)) + "@" +
                   centre_text(index, source.topo_id) + "->" + upper(kind_name(e.ref.kind)) + "@" +
                   centre_text(index, e.ref.topo_id));
  }
  for (const TopoRoleEntry& r : delta.roles) {
    std::string parent = "-";
    if (!r.parent_refs.empty()) {
      parent = upper(kind_name(r.parent_refs[0].kind)) + "@" + centre_text(index, r.parent_refs[0].topo_id);
    }
    body.push_back("R " + r.role + "|" + r.origin_role.value_or("-") + "|" +
                   r.metadata.find("evidence_method")->as_string() + "|" + upper(kind_name(r.ref.kind)) + "@" +
                   centre_text(index, r.ref.topo_id) + "|" + parent);
  }
  for (const TopoRef& ref : delta.section_edges) body.push_back("S EDGE@" + centre_text(index, ref.topo_id));
  for (const auto& [id, value] : entries) {
    body.push_back("D " + centre_text(index, id) + "|" + value.find("kind")->as_string() + "|ev=" +
                   join(value.find("events")) + "|or=" + join(value.find("origin_roles")) +
                   "|rr=" + join(value.find("result_roles")) + "|w=" +
                   std::to_string(value.find("witnesses")->size()));
  }
  std::sort(body.begin(), body.end());
  lines.insert(lines.end(), body.begin(), body.end());
  return lines;
}

}  // namespace scad::tracking_test
