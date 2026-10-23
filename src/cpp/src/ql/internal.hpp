// Internals shared by the src/ql translation units.  Not installed.
#pragma once

#include <string_view>
#include <vector>

#include "scad/ql/identity.hpp"
#include "scad/ql/scope.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql::detail {

// First occurrence wins, order kept.
[[nodiscard]] std::vector<Shape> dedupe(std::vector<Shape> items);

// The candidates a selector of `target_kind` starts from inside `scope`
// (_resolve_scope_items).  TypeError when the scope has no such entities to offer.
[[nodiscard]] std::vector<Shape> scope_items(const Scope& scope, std::string_view target_kind);

// The `target_kind` sub-shapes bounding `item` (_boundary_items).
[[nodiscard]] std::vector<Shape> boundary_items(const Shape& item, std::string_view target_kind);

[[nodiscard]] std::vector<Shape> traverse_items(const std::vector<Shape>& items, std::string_view target_kind);

[[nodiscard]] bool is_traversal_kind(std::string_view kind) noexcept;

}  // namespace scad::ql::detail
