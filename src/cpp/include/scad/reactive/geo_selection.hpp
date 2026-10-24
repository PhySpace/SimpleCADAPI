// How a pick (a face, an edge, ... of a recorded output) is written into the operation graph:
// the ports of operators/_support.py's `_make_geo_selector`, `_make_selector_hint`,
// `_serialize_shape_ref(s)` and `_serialize_selection_indices`.
//
// The payloads are part of the model-JSON contract (the translators and the strict replay read
// them), so key order, value types and number types are those of the Python SDK.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

// "vertex" / "edge" / "wire" / "face" / "shell" / "solid" / "compound" (_shape_kind_token).
std::string shape_kind_token(const Shape& shape);

// "LINE" / "CIRCLE" / ... for an edge, "PLANE" / "CYLINDER" / ... for a face (_shape_geom_type).
std::optional<std::string> shape_geom_type(const Shape& shape);

// {"kind", "tags", <measurements>}: what a reader needs to find the shape again when its
// reference no longer resolves (_make_selector_hint).
Value make_selector_hint(const Shape& shape);

// The "geo_exact" selector of a select node's `geo_selector` param (_make_geo_selector).
// `source` is the shape the pick was made from: it fixes the `edge_index` the SDK's wrappers carry.
Value make_geo_exact_selector(const Shape& shape, const Shape* source = nullptr);

// The reference of a recorded shape with its selector hint, or nullopt for a shape that is not
// part of a recorded output (_serialize_shape_ref).
std::optional<Value> serialize_shape_ref(const Shape& shape);
// One reference per shape that has one, in order (_serialize_shape_refs).
Value serialize_shape_refs(const std::vector<Shape>& shapes);
std::optional<std::string> shape_ref_topo_id(const Shape& shape);

// Positions in `candidates` of the shapes of `selected` (by topo id), skipping the ones not found
// (_serialize_selection_indices).
Value serialize_selection_indices(const std::vector<Shape>& selected, const std::vector<Shape>& candidates);

template <class T>
std::vector<Shape> as_shapes(const std::vector<T>& items) {
  return std::vector<Shape>(items.begin(), items.end());
}

}  // namespace scad::reactive
