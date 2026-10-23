// The representation of ql::ShapeSelector, shared by selector.cpp and resolve.cpp.  Not installed.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/ql/selector.hpp"

namespace scad::ql {

struct ShapeSelector::Impl {
  std::string target_kind;
  std::optional<ShapeSelector> source_selector;
  std::optional<TraversalSpec> traversal;
  std::optional<Predicate> predicate;
  std::optional<Key> order_key;
  std::vector<std::pair<Key, bool>> order_keys;
  bool order_desc = false;
  std::optional<std::int64_t> limit_count;
  std::vector<std::pair<std::string, std::int64_t>> cardinality;
  std::optional<std::string> source_node_id;
  std::optional<int> source_output_slot;
  std::optional<std::string> set_operation;
  std::vector<ShapeSelector> operands;
  std::vector<ShapeSelector> incident_face_selectors;
  bool incident_faces_distinct = false;
  std::optional<std::int64_t> incident_face_cardinality;
};

}  // namespace scad::ql
