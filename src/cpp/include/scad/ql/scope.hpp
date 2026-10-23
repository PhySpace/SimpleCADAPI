// What a selector reads from: one shape, or an explicit list of shapes.
//
// ql.faces().resolve(solid) enumerates the solid's faces; ql.solids().resolve([a, b])
// takes the listed shapes as the candidates themselves, whatever their kind.
#pragma once

#include <concepts>
#include <type_traits>
#include <variant>
#include <vector>

#include "scad/topo/shape.hpp"

namespace scad::ql {

class Scope {
 public:
  Scope(const Shape& shape) : data_(shape) {}                 // NOLINT(google-explicit-constructor)
  Scope(std::vector<Shape> items) : data_(std::move(items)) {}  // NOLINT(google-explicit-constructor)
  template <class T>
    requires(std::derived_from<T, Shape> && !std::is_same_v<T, Shape>)
  Scope(const std::vector<T>& items)  // NOLINT(google-explicit-constructor)
      : data_(std::vector<Shape>(items.begin(), items.end())) {}

  [[nodiscard]] bool is_list() const noexcept { return std::holds_alternative<std::vector<Shape>>(data_); }
  // Precondition: !is_list().
  [[nodiscard]] const Shape& shape() const { return std::get<Shape>(data_); }
  // Precondition: is_list().
  [[nodiscard]] const std::vector<Shape>& items() const { return std::get<std::vector<Shape>>(data_); }

 private:
  std::variant<Shape, std::vector<Shape>> data_;
};

}  // namespace scad::ql
