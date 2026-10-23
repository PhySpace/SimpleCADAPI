// Query / select: the eager list-based cousin of ShapeSelector.
//
//   ql::select(faces).where(ql::tag("face.top")).order_by(ql::geo("area"), true).first()
//
// Works over shapes you already hold; where() and order_by() take any callable,
// including a Predicate or a Key.
#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

class Query {
 public:
  using Test = std::function<bool(const Shape&)>;
  using KeyFn = std::function<Value(const Shape&)>;

  explicit Query(std::vector<Shape> items) : items_(std::move(items)) {}

  [[nodiscard]] Query where(const Test& test) const;
  // Stable; items whose key is null sort last (first when desc).  Keys of
  // unrelated types are a TypeError, as in Python.
  [[nodiscard]] Query order_by(const KeyFn& sort_key, bool desc = false) const;
  // count <= 0 gives an empty query.
  [[nodiscard]] Query limit(std::int64_t count) const;
  [[nodiscard]] std::optional<Shape> first() const;
  [[nodiscard]] const std::vector<Shape>& all() const noexcept { return items_; }

 private:
  std::vector<Shape> items_;
};

template <class T>
[[nodiscard]] Query select(const std::vector<T>& items) {
  return Query(std::vector<Shape>(items.begin(), items.end()));
}

}  // namespace scad::ql
