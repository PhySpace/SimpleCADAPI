// Shared checks of the std tests.
#pragma once

#include <algorithm>
#include <string>
#include <string_view>

#include "doctest.h"
#include "scad/core/error.hpp"
#include "scad/std/std.hpp"
#include "scad/topo/shape.hpp"

namespace scad::std_test {

inline bool has_tag(const Shape& shape, std::string_view tag) {
  return shape.has_tag(tag, TagScope::Effective);
}

inline double radial_extent(const Solid& solid) {
  const auto box = solid.bounding_box();
  return std::max({std::fabs(box.xmin), std::fabs(box.xmax), std::fabs(box.ymin), std::fabs(box.ymax)});
}

// The message of the ValueError (or Error) `call` throws; fails the test when it does not throw.
template <class F>
std::string failure_message(F&& call) {
  try {
    call();
  } catch (const std::exception& e) {
    return e.what();
  }
  FAIL("the call did not fail");
  return {};
}

template <class F>
Error operator_failure(F&& call) {
  try {
    call();
  } catch (const Error& e) {
    return e;
  }
  FAIL("the call did not raise a scad::Error");
  throw 0;
}

inline double number(const Value& dict, std::string_view key) {
  return dict.find(key)->as_double();
}

}  // namespace scad::std_test
