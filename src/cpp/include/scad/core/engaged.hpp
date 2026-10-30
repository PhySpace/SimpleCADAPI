// Access to an optional that an invariant of the surrounding data says is engaged.
//
// `require_engaged(value, "why it is engaged")` is `*value` with the check written down: an optional that
// turns out empty is a broken internal invariant, reported as a RuntimeError naming the invariant instead
// of undefined behaviour.  The check lives in one place so that every call site stays one line and the
// static analyser sees the dominating test.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "scad/core/error.hpp"

namespace scad {

namespace engaged_detail {
[[noreturn]] inline void broken_invariant(std::string_view invariant) {
  throw RuntimeError("internal invariant violated: " + std::string(invariant));
}
}  // namespace engaged_detail

template <class T>
const T& require_engaged(const std::optional<T>& value, std::string_view invariant) {
  if (!value)
    engaged_detail::broken_invariant(invariant);
  return *value;
}

template <class T>
T& require_engaged(std::optional<T>& value, std::string_view invariant) {
  if (!value)
    engaged_detail::broken_invariant(invariant);
  return *value;
}

// A temporary optional: the value is moved out, never referenced after the temporary dies.
template <class T>
T require_engaged(std::optional<T>&& value, std::string_view invariant) {
  if (!value)
    engaged_detail::broken_invariant(invariant);
  return std::move(*value);
}

}  // namespace scad
