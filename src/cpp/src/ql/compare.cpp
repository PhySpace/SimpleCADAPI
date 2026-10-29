#include "scad/ql/compare.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "scad/core/error.hpp"

namespace scad::ql {

namespace {

bool numeric(const Value& v) noexcept {
  return v.is_bool() || v.is_int() || v.is_double();
}
bool integral(const Value& v) noexcept {
  return v.is_bool() || v.is_int();
}

std::int64_t as_integer(const Value& v) {
  return v.is_bool() ? (v.as_bool() ? 1 : 0) : v.as_int();
}
double as_real(const Value& v) {
  return v.is_double() ? v.as_double() : static_cast<double>(as_integer(v));
}

template <class T>
Ordering three_way(const T& a, const T& b) {
  return a < b ? Ordering::Less : (b < a ? Ordering::Greater : Ordering::Equal);
}

Ordering compare_numbers(const Value& a, const Value& b) {
  if (integral(a) && integral(b))
    return three_way(as_integer(a), as_integer(b));
  const double x = as_real(a);
  const double y = as_real(b);
  if (std::isnan(x) || std::isnan(y))
    return Ordering::Unordered;
  return three_way(x, y);
}

// The shortest %.Ng that reads back as the same double (Python's repr, give or take the exponent style).
std::string shortest_double(double v) {
  if (std::isnan(v))
    return "nan";
  if (std::isinf(v))
    return v < 0 ? "-inf" : "inf";
  char buf[40];
  for (int precision = 1; precision <= 17; ++precision) {
    std::snprintf(buf, sizeof buf, "%.*g", precision, v);
    if (std::strtod(buf, nullptr) == v)
      break;
  }
  std::string text = buf;
  if (text.find_first_of(".eE") == std::string::npos)
    text += ".0";
  return text;
}

std::string repr_of(const Value& v) {
  if (v.is_string())
    return "'" + v.as_string() + "'";
  return py_str(v);
}

}  // namespace

bool values_equal(const Value& a, const Value& b) {
  if (numeric(a) && numeric(b))
    return compare_numbers(a, b) == Ordering::Equal;
  if (a.is_null() && b.is_null())
    return true;
  if (a.is_string() && b.is_string())
    return a.as_string() == b.as_string();
  if (a.is_array() && b.is_array()) {
    const auto& x = a.as_array();
    const auto& y = b.as_array();
    if (x.size() != y.size())
      return false;
    for (std::size_t i = 0; i < x.size(); ++i)
      if (!values_equal(x[i], y[i]))
        return false;
    return true;
  }
  if (a.is_object() && b.is_object()) {
    const auto& x = a.as_object();
    if (x.size() != b.size())
      return false;
    for (const auto& [name, item] : x) {
      const Value* other = b.find(name);
      if (other == nullptr || !values_equal(item, *other))
        return false;
    }
    return true;
  }
  return false;
}

Ordering compare_values(const Value& a, const Value& b) {
  if (numeric(a) && numeric(b))
    return compare_numbers(a, b);
  if (a.is_string() && b.is_string())
    return three_way(a.as_string(), b.as_string());
  if (a.is_null() && b.is_null())
    return Ordering::Equal;
  if (a.is_array() && b.is_array()) {
    const auto& x = a.as_array();
    const auto& y = b.as_array();
    const std::size_t common = std::min(x.size(), y.size());
    for (std::size_t i = 0; i < common; ++i) {
      const Ordering step = compare_values(x[i], y[i]);
      if (step != Ordering::Equal)
        return step;
    }
    return three_way(x.size(), y.size());
  }
  if (a.is_object() && b.is_object() && values_equal(a, b))
    return Ordering::Equal;
  return Ordering::Incomparable;
}

std::string_view py_type_name(const Value& v) noexcept {
  if (v.is_null())
    return "NoneType";
  if (v.is_bool())
    return "bool";
  if (v.is_int())
    return "int";
  if (v.is_double())
    return "float";
  if (v.is_string())
    return "str";
  if (v.is_array())
    return "list";
  return "dict";
}

std::string py_str(const Value& v) {
  if (v.is_null())
    return "None";
  if (v.is_bool())
    return v.as_bool() ? "True" : "False";
  if (v.is_int())
    return std::to_string(v.as_int());
  if (v.is_double())
    return shortest_double(v.as_double());
  if (v.is_string())
    return v.as_string();
  if (v.is_array()) {
    std::string out = "[";
    bool first = true;
    for (const Value& item : v.as_array()) {
      if (!first)
        out += ", ";
      first = false;
      out += repr_of(item);
    }
    return out + "]";
  }
  std::string out = "{";
  bool first = true;
  for (const auto& [name, item] : v.as_object()) {
    if (!first)
      out += ", ";
    first = false;
    out += "'" + name + "': " + repr_of(item);
  }
  return out + "}";
}

CompareOp parse_compare_op(std::string_view text) noexcept {
  if (text == "==")
    return CompareOp::Eq;
  if (text == "!=")
    return CompareOp::Ne;
  if (text == ">")
    return CompareOp::Gt;
  if (text == ">=")
    return CompareOp::Ge;
  if (text == "<")
    return CompareOp::Lt;
  if (text == "<=")
    return CompareOp::Le;
  return CompareOp::Unsupported;
}

bool compare(const Value& actual, CompareOp op, std::string_view op_text, const Value& expected) {
  if (op == CompareOp::Eq)
    return values_equal(actual, expected);
  if (op == CompareOp::Ne)
    return !values_equal(actual, expected);
  if (actual.is_null())
    return false;
  if (op == CompareOp::Unsupported)
    throw ValueError("unsupported op: " + std::string(op_text));
  const Ordering order = compare_values(actual, expected);
  switch (op) {
    case CompareOp::Gt:
      return order == Ordering::Greater;
    case CompareOp::Ge:
      return order == Ordering::Greater || order == Ordering::Equal;
    case CompareOp::Lt:
      return order == Ordering::Less;
    case CompareOp::Le:
      return order == Ordering::Less || order == Ordering::Equal;
    default:
      return false;
  }
}

}  // namespace scad::ql
