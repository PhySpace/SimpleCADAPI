// The validation every product value shares (simplecadapi/_internal/semantic.py and the
// field checks of product/placement.py).  Messages are the Python ones: callers and
// agents read them.
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/reactive/errors.hpp"

namespace scad::product {

using OptionalString = std::optional<std::string>;
using OptionalDouble = std::optional<double>;

// ValueError unless `value` is non-empty after trimming and matches
// [A-Za-z][A-Za-z0-9_.:-]*.  Returns the trimmed text.
std::string validate_identifier(std::string_view value, std::string_view field);

// What Python's float(x) gives for an argument that may be a Var / Expr.  NaN and infinity
// pass through: the value that consumes the number says "<field> must be finite".
double scalar_float(const Scalar& value);

// ValueError "<field> must be finite".
double finite_float(double value, std::string_view field);
OptionalDouble optional_float(OptionalDouble value, std::string_view field);
// ... and "<field> must be positive" for a value <= 0.
OptionalDouble optional_positive_float(OptionalDouble value, std::string_view field);

// ValueError when every component is not finite ("<field>[i] must be finite").
Vec3 finite_vec3(const Vec3& value, std::string_view field);

// A display name: trimmed; ValueError "name must not be empty when provided".
OptionalString clean_name(const OptionalString& name);

// Python's str.strip() for ASCII whitespace.
std::string strip(std::string_view text);

// repr() of a Python str: what str(KeyError(message)) shows.
std::string python_repr(std::string_view text);

// A lookup that failed ("assembly has no component_id 'x'").  Python's KeyError: its text, as
// str() renders it, is the repr of the message (see key_error_text).
class LookupError : public reactive::KeyError {
 public:
  using reactive::KeyError::KeyError;
};

// "<message repr>" for a LookupError / KeyError, what() otherwise: the text Python's
// str(exception) gives.
std::string exception_text(const std::exception& error);

// Value of a Vec3 as a three-element array.
Value to_array(const Vec3& v);

}  // namespace scad::product
