// Python's comparison semantics over Value.
//
// QL predicates compare metadata and measured properties with ==, !=, <, ...
// exactly as the Python SDK does on Python objects: 7 == 7.0, True == 1,
// strings and lists order lexicographically, and operands of unrelated types
// are not orderable (a comparison of those is false, a sort of those raises).
#pragma once

#include <string>
#include <string_view>

#include "scad/core/value.hpp"

namespace scad::ql {

// Unordered: both operands are numbers but one is NaN (every ordering test is false).
// Incomparable: Python would raise TypeError for `<` on these operands.
enum class Ordering { Less, Equal, Greater, Unordered, Incomparable };

[[nodiscard]] bool values_equal(const Value& a, const Value& b);
[[nodiscard]] Ordering compare_values(const Value& a, const Value& b);

// str(value) and type(value).__name__ as Python would print them.
[[nodiscard]] std::string py_str(const Value& v);
[[nodiscard]] std::string_view py_type_name(const Value& v) noexcept;

enum class CompareOp { Eq, Ne, Gt, Ge, Lt, Le, Unsupported };
[[nodiscard]] CompareOp parse_compare_op(std::string_view text) noexcept;

// _compare(actual, op, value).  A missing `actual` (null) only ever satisfies
// == / !=; an unsupported operator is a ValueError once there is something to
// compare.
[[nodiscard]] bool compare(const Value& actual, CompareOp op, std::string_view op_text, const Value& expected);

}  // namespace scad::ql
