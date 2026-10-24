// How a product operator fails: every public operator wraps its body so that any exception
// leaves as the operation's structured Error.  A KeyError is described the way Python's
// str(KeyError) shows it (the repr of the message).
#pragma once

#include <string>
#include <string_view>
#include <utility>

#include "scad/core/error.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

// The static guidance of a public operator ("make_part_rpart", "add_gear_constraint_rassembly", ...).
// KeyError for a name that is not a guarded operator.
const ErrorSpec& operator_spec(std::string_view operation);

// Throws the Error `operation` raises for `error`.
[[noreturn]] void raise_operation_error(std::string_view operation, const std::exception& error);

template <class F>
decltype(auto) guard_operation(std::string_view operation, F&& body) {
  try {
    return std::forward<F>(body)();
  } catch (const Error&) {
    throw;
  } catch (const std::exception& error) {
    raise_operation_error(operation, error);
  }
}

}  // namespace scad::product
