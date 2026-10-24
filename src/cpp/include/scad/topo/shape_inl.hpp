// Inline parts of shape.hpp.
#pragma once

#include <string>

#include "scad/core/error.hpp"

namespace scad {

template <class T>
const T& pick(const std::vector<T>& items, long index, std::string_view what) {
  const long n = static_cast<long>(items.size());
  const long i = index < 0 ? index + n : index;
  if (i < 0 || i >= n) {
    throw IndexError(std::string(what) + " index " + std::to_string(index) +
                     " is out of range for " + std::to_string(n) + " item(s)");
  }
  return items[static_cast<std::size_t>(i)];
}

}  // namespace scad
