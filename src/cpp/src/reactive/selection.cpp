// Selection operations: a face or edge picked from an operation's result is a
// node of its own, so that what depends on the pick recomputes when its
// source does.  The node records where the pick was (index among the source's
// sub-shapes of that kind, centre, box) and re-finds it in the rebuilt source.
#include <cmath>
#include <limits>

#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "internal.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/reactive/geo_selection.hpp"

namespace scad::reactive::detail {

namespace {

TopAbs_ShapeEnum topabs(Kind kind) {
  switch (kind) {
    case Kind::Vertex:
      return TopAbs_VERTEX;
    case Kind::Edge:
      return TopAbs_EDGE;
    case Kind::Wire:
      return TopAbs_WIRE;
    case Kind::Face:
      return TopAbs_FACE;
    case Kind::Shell:
      return TopAbs_SHELL;
    case Kind::Solid:
      return TopAbs_SOLID;
    case Kind::Compound:
      return TopAbs_COMPOUND;
  }
  return TopAbs_SHAPE;
}

Vec3 vec_of(const Value* value) {
  if (value == nullptr || !value->is_array() || value->size() != 3)
    return {};
  const auto& a = value->as_array();
  return {a[0].as_double(), a[1].as_double(), a[2].as_double()};
}

bool has_vec(const Value* value) {
  return value != nullptr && value->is_array() && value->size() == 3;
}

Kind kind_from_name(std::string_view name) {
  for (const Kind k : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    if (kind_name(k) == name)
      return k;
  }
  throw ValueError("unknown shape kind '" + std::string(name) + "' in a selection");
}

double number_or(const Value* value, double fallback) {
  return value != nullptr && value->is_number() ? value->as_double() : fallback;
}

// _geo_selector_score: how far `shape` is from what the selector describes (0 = the same).
double geo_selector_score(const Shape& shape, const Value& selector) {
  const Value* kind = selector.find("kind");
  if (kind == nullptr || !kind->is_string() || kind->as_string() != kind_name(shape.kind()))
    return 1e12;

  double score = 0.0;
  if (const Value* bbox = selector.find("bbox"); bbox != nullptr && bbox->is_object()) {
    const Value* lo = bbox->find("min");
    const Value* hi = bbox->find("max");
    if (!has_vec(lo) || !has_vec(hi)) {
      score = 1e6;
    } else {
      const kernel::BoundingBox box = kernel::bounding_box(shape.wrapped());
      score = Vec3{box.xmin, box.ymin, box.zmin}.distance(vec_of(lo)) +
              Vec3{box.xmax, box.ymax, box.zmax}.distance(vec_of(hi));
    }
  }
  score *= 10.0;
  if (const Value* expected = selector.find("geom_type"); expected != nullptr && expected->is_string()) {
    const auto actual = shape_geom_type(shape);
    if (actual && *actual != expected->as_string())
      score += 1e6;
  }
  const auto center_term = [&](double weight) {
    return has_vec(selector.find("center")) ? shape.center().distance(vec_of(selector.find("center"))) * weight : 1e6;
  };
  switch (shape.kind()) {
    case Kind::Vertex:
      score += has_vec(selector.find("coordinates"))
                   ? shape.as<Vertex>().coordinates().distance(vec_of(selector.find("coordinates"))) * 10.0
                   : 1e6;
      break;
    case Kind::Edge: {
      const Edge edge = shape.as<Edge>();
      if (const Value* length = selector.find("length"))
        score += std::abs(edge.length() - number_or(length, 0.0)) * 10.0;
      score += center_term(10.0);
      try {
        const Vec3 start = edge.start_vertex().coordinates();
        const Vec3 end = edge.end_vertex().coordinates();
        if (has_vec(selector.find("start")) && has_vec(selector.find("end"))) {
          const Vec3 s = vec_of(selector.find("start")), e = vec_of(selector.find("end"));
          score += std::min(start.distance(s) + end.distance(e), start.distance(e) + end.distance(s));
        }
      } catch (const std::exception&) {
      }
      break;
    }
    case Kind::Wire: {
      const Wire wire = shape.as<Wire>();
      if (const Value* n = selector.find("edge_count"))
        score += std::abs(static_cast<double>(wire.edges().size()) - number_or(n, 0.0)) * 10.0;
      if (const Value* closed = selector.find("closed");
          closed != nullptr && closed->is_bool() && closed->as_bool() != wire.is_closed())
        score += 10.0;
      break;
    }
    case Kind::Face: {
      const Face face = shape.as<Face>();
      if (const Value* area = selector.find("area"))
        score += std::abs(face.area() - number_or(area, 0.0));
      score += center_term(10.0);
      score +=
          has_vec(selector.find("normal")) ? face.normal_at().distance(vec_of(selector.find("normal"))) * 5.0 : 1e6;
      if (const Value* n = selector.find("edge_count"))
        score += std::abs(static_cast<double>(face.edges().size()) - number_or(n, 0.0)) * 10.0;
      if (const Value* n = selector.find("inner_wire_count"))
        score += std::abs(static_cast<double>(face.inner_wires().size()) - number_or(n, 0.0)) * 10.0;
      break;
    }
    case Kind::Shell:
      if (const Value* n = selector.find("face_count"))
        score += std::abs(static_cast<double>(shape.as<Shell>().faces().size()) - number_or(n, 0.0)) * 10.0;
      break;
    case Kind::Solid:
      if (const Value* v = selector.find("volume"))
        score += std::abs(shape.as<Solid>().volume() - number_or(v, 0.0));
      break;
    case Kind::Compound:
      break;
  }
  return score;
}

}  // namespace

TopAbs_ShapeEnum topabs_of(Kind kind) {
  return topabs(kind);
}

std::string kind_token(const Shape& shape) {
  return std::string(kind_name(shape.kind()));
}

std::string selection_op_name(Kind kind) {
  switch (kind) {
    case Kind::Vertex:
      return "make_select_rvertex";
    case Kind::Edge:
      return "make_select_redge";
    case Kind::Wire:
      return "make_select_rwire";
    case Kind::Face:
      return "make_select_rface";
    case Kind::Shell:
      return "make_select_rshell";
    case Kind::Solid:
      return "make_select_rsolid";
    case Kind::Compound:
      return {};
  }
  return {};
}

std::optional<std::size_t> topo_index(std::string_view topo_id) {
  const std::size_t underscore = topo_id.rfind('_');
  if (underscore == std::string_view::npos || underscore + 1 >= topo_id.size())
    return std::nullopt;
  std::size_t index = 0;
  for (const char c : topo_id.substr(underscore + 1)) {
    if (c < '0' || c > '9')
      return std::nullopt;
    index = index * 10 + static_cast<std::size_t>(c - '0');
  }
  return index;
}

std::optional<std::pair<std::int64_t, std::int64_t>> index_in_source(const Shape& source, const Shape& picked) {
  TopTools_IndexedMapOfShape map;
  TopExp::MapShapes(source.wrapped(), topabs(picked.kind()), map);
  const int found = map.FindIndex(picked.wrapped());
  if (found <= 0)
    return std::nullopt;
  return std::pair<std::int64_t, std::int64_t>{found - 1, map.Extent()};
}

Shape resolve_geo_selector(const Shape& source, const Value& selector,
                           const std::optional<std::pair<std::int64_t, std::int64_t>>& index) {
  const Value* kind_value = selector.find("kind");
  if (kind_value == nullptr)
    kind_value = selector.find("target_kind");
  if (kind_value == nullptr || !kind_value->is_string())
    throw ValueError("geometric selector has no kind");
  const Kind kind = kind_from_name(kind_value->as_string());
  TopTools_IndexedMapOfShape map;
  TopExp::MapShapes(source.wrapped(), topabs(kind), map);
  if (map.Extent() == 0) {
    throw ValueError("the rebuilt source has no " + std::string(kind_name(kind)) + " left to select");
  }
  if (index && index->second == map.Extent() && index->first >= 0 && index->first < map.Extent()) {
    return source.sub(map(static_cast<int>(index->first) + 1));
  }
  int best = 1;
  double best_score = std::numeric_limits<double>::infinity();
  for (int i = 1; i <= map.Extent(); ++i) {
    const double score = geo_selector_score(source.sub(map(i)), selector);
    if (score < best_score) {
      best_score = score;
      best = i;
    }
  }
  return source.sub(map(best));
}

void register_selection_executors(ExecutorRegistry& registry) {
  for (const Kind kind : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid}) {
    registry.add(
        selection_op_name(kind), [](const Value& params, const std::vector<OpInput>& inputs, const ScalarValues&) {
          if (inputs.size() != 1)
            throw ValueError("a selection takes exactly one source");
          const Value* selector = params.find("geo_selector");
          if (selector == nullptr)
            throw ValueError("a selection records no geo_selector");
          std::optional<std::pair<std::int64_t, std::int64_t>> index;
          if (const Value* at = params.find("__source_index"); at != nullptr && at->is_array() && at->size() == 2)
            index = std::pair<std::int64_t, std::int64_t>{at->as_array()[0].as_int(), at->as_array()[1].as_int()};
          return std::vector<Shape>{resolve_geo_selector(inputs.front().shape, *selector, index)};
        });
  }
}

}  // namespace scad::reactive::detail
