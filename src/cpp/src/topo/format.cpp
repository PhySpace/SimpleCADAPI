// Shape::repr / to_string: the text the Python SDK prints for each kind.
#include <algorithm>
#include <cstdio>

#include "scad/core/error.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

namespace {

std::string f3(double v) {
  char buf[64];
  std::snprintf(buf, sizeof buf, "%.3f", v);
  return buf;
}

std::string g6(double v) {
  char buf[64];
  std::snprintf(buf, sizeof buf, "%.6g", v);
  return buf;
}

std::string vec_repr(const Vec3& v) {
  return "Vec3(" + g6(v.x) + ", " + g6(v.y) + ", " + g6(v.z) + ")";
}

std::string tag_list(const Shape& s) {
  std::string out = "[";
  bool first = true;
  for (const auto& t : s.list_tags()) {
    if (!first)
      out += ", ";
    first = false;
    out += "'" + t + "'";
  }
  return out + "]";
}

std::string spaces(int indent) {
  return std::string(static_cast<std::size_t>(indent) * 2, ' ');
}

std::string tags_and_metadata(const Shape& s, int indent) {
  const std::string pad = spaces(indent);
  std::string out;
  const auto tags = s.list_tags();
  if (!tags.empty()) {
    out += pad + "tags: [";
    for (std::size_t i = 0; i < tags.size(); ++i)
      out += (i ? ", " : "") + tags[i];
    out += "]";
  }
  const Value& meta = s.metadata();
  if (meta.is_object() && meta.size() > 0) {
    auto members = meta.as_object();
    std::sort(members.begin(), members.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    if (!out.empty())
      out += "\n";
    out += pad + "metadata:";
    for (const auto& [key, value] : members)
      out += "\n" + pad + "  " + key + ": " + value.dump();
  }
  return out;
}

void append(std::string& out, const std::string& line) {
  if (line.empty())
    return;
  if (!out.empty())
    out += "\n";
  out += line;
}

}  // namespace

std::string Shape::repr() const {
  switch (kind()) {
    case Kind::Vertex: {
      const Vec3 c = Vertex(*this).coordinates();
      return "Vertex(coordinates=(" + g6(c.x) + ", " + g6(c.y) + ", " + g6(c.z) + "))";
    }
    case Kind::Edge: {
      const Edge e(*this);
      std::string ends;
      try {
        const Vec3 a = e.start_vertex().coordinates(), b = e.end_vertex().coordinates();
        ends = "from: (" + g6(a.x) + ", " + g6(a.y) + ", " + g6(a.z) + "), to: (" + g6(b.x) + ", " + g6(b.y) + ", " +
               g6(b.z) + ")";
      } catch (const std::exception&) {
        ends = "from: [unable to retrieve], to: [unable to retrieve], usually this is a closed edge";
      }
      return "Edge(" + ends + ", length=" + f3(e.length()) + ", tags=" + tag_list(*this) + ")";
    }
    case Kind::Wire: {
      const Wire w(*this);
      return "Wire(edge_count=" + std::to_string(w.edges().size()) + ", closed=" + (w.is_closed() ? "True" : "False") +
             ", tags=" + tag_list(*this) + ")";
    }
    case Kind::Face: {
      const Face f(*this);
      return "Face(area=" + f3(f.area()) + ", normal=" + vec_repr(f.normal_at()) + ", center=" + vec_repr(f.center()) +
             ", tags=" + tag_list(*this) + ")";
    }
    case Kind::Shell: {
      const Shell s(*this);
      return "Shell(faces=" + std::to_string(s.faces().size()) + ", area=" + f3(s.area()) +
             ", closed=" + (s.is_closed() ? "True" : "False") + ", tags=" + tag_list(*this) + ")";
    }
    case Kind::Solid: {
      const Solid s(*this);
      return "Solid(volume=" + f3(s.volume()) + ", faces=" + std::to_string(s.faces().size()) +
             ", tags=" + tag_list(*this) + ")";
    }
    case Kind::Compound: {
      const Compound c(*this);
      return "Compound(solids=" + std::to_string(c.solids().size()) + ", volume=" + f3(c.volume()) +
             ", tags=" + tag_list(*this) + ")";
    }
  }
  return "Shape()";
}

std::string Shape::to_string(int indent) const {
  const std::string pad = spaces(indent);
  std::string out;
  switch (kind()) {
    case Kind::Vertex: {
      const Vec3 c = Vertex(*this).coordinates();
      append(out, pad + "Vertex:");
      append(out, pad + "  coordinates: [" + f3(c.x) + ", " + f3(c.y) + ", " + f3(c.z) + "]");
      break;
    }
    case Kind::Edge: {
      const Edge e(*this);
      append(out, pad + "Edge:");
      append(out, pad + "  length: " + f3(e.length()));
      try {
        const Vec3 a = e.start_vertex().coordinates(), b = e.end_vertex().coordinates();
        append(out, pad + "  vertices:");
        append(out, pad + "    start: (" + g6(a.x) + ", " + g6(a.y) + ", " + g6(a.z) + ")");
        append(out, pad + "    end: (" + g6(b.x) + ", " + g6(b.y) + ", " + g6(b.z) + ")");
      } catch (const std::exception&) {
        append(out, pad + "  vertices: [unable to retrieve, usually a closed edge]");
      }
      break;
    }
    case Kind::Wire: {
      const Wire w(*this);
      const auto edges = w.edges();
      append(out, pad + "Wire:");
      append(out, pad + "  edge_count: " + std::to_string(edges.size()));
      append(out, pad + std::string("  closed: ") + (w.is_closed() ? "True" : "False"));
      if (!edges.empty()) {
        append(out, pad + "  edges:");
        for (std::size_t i = 0; i < edges.size(); ++i) {
          append(out, pad + "    edge_" + std::to_string(i) + ":");
          append(out, edges[i].to_string(indent + 3));
        }
      }
      break;
    }
    case Kind::Face: {
      const Face f(*this);
      append(out, pad + "Face:");
      append(out, pad + "  area: " + f3(f.area()) + ", center: " + vec_repr(f.center()));
      try {
        const Vec3 n = f.normal_at();
        append(out, pad + "  normal: [" + f3(n.x) + ", " + f3(n.y) + ", " + f3(n.z) + "]");
      } catch (const std::exception&) {
        append(out, pad + "  normal: [unable to retrieve]");
      }
      try {
        append(out, pad + "  outer_wire:");
        append(out, f.outer_wire().to_string(indent + 2));
      } catch (const std::exception&) {
        append(out, pad + "  outer_wire: [unable to retrieve]");
      }
      try {
        for (const Wire& inner : f.inner_wires()) {
          append(out, pad + "  inner_wire:");
          append(out, inner.to_string(indent + 2));
        }
      } catch (const std::exception&) {
        append(out, pad + "  inner_wires: [unable to retrieve]");
      }
      break;
    }
    case Kind::Shell:
      return repr();
    case Kind::Solid: {
      const Solid s(*this);
      const auto faces = s.faces();
      append(out, pad + "Solid:");
      append(out, pad + "  volume: " + f3(s.volume()));
      append(out, pad + "  face_count: " + std::to_string(faces.size()));
      append(out, pad + "  edge_count: " + std::to_string(s.edges().size()));
      if (!faces.empty()) {
        append(out, pad + "  faces:");
        for (std::size_t i = 0; i < faces.size(); ++i) {
          append(out, pad + "    face_" + std::to_string(i) + ":");
          append(out, faces[i].to_string(indent + 3));
        }
      }
      break;
    }
    case Kind::Compound: {
      const Compound c(*this);
      append(out, pad + "Compound:");
      append(out, pad + "  solid_count: " + std::to_string(c.solids().size()));
      append(out, pad + "  volume: " + f3(c.volume()));
      break;
    }
  }
  append(out, tags_and_metadata(*this, indent + 1));
  return out;
}

}  // namespace scad
