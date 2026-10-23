#include "scad/product/validation.hpp"

#include <cmath>
#include <cstdio>

#include "scad/core/error.hpp"

namespace scad::product {

namespace {

bool is_space(char c) {
  return c == ' ' || (c >= '\t' && c <= '\r') || (c >= '\x1c' && c <= '\x1f');
}

bool is_alpha(char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z'); }
bool is_digit(char c) { return c >= '0' && c <= '9'; }

}  // namespace

std::string strip(std::string_view text) {
  while (!text.empty() && is_space(text.front())) text.remove_prefix(1);
  while (!text.empty() && is_space(text.back())) text.remove_suffix(1);
  return std::string(text);
}

std::string validate_identifier(std::string_view value, std::string_view field) {
  const std::string text = strip(value);
  const std::string label(field);
  if (text.empty()) throw ValueError(label + " must not be empty");
  bool valid = is_alpha(text.front());
  for (const char c : text) {
    valid = valid && (is_alpha(c) || is_digit(c) || c == '_' || c == '.' || c == ':' || c == '-');
  }
  if (!valid) {
    throw ValueError(label +
                     " must start with a letter and contain only letters, digits, underscore, dash, dot, or colon");
  }
  return text;
}

double scalar_float(const Scalar& value) { return value.symbolic() ? value.value() : value.literal(); }

double finite_float(double value, std::string_view field) {
  if (!std::isfinite(value)) throw ValueError(std::string(field) + " must be finite");
  return value;
}

OptionalDouble optional_float(OptionalDouble value, std::string_view field) {
  if (value) finite_float(*value, field);
  return value;
}

OptionalDouble optional_positive_float(OptionalDouble value, std::string_view field) {
  optional_float(value, field);
  if (value && *value <= 0.0) throw ValueError(std::string(field) + " must be positive");
  return value;
}

Vec3 finite_vec3(const Vec3& value, std::string_view field) {
  const std::string label(field);
  finite_float(value.x, label + "[0]");
  finite_float(value.y, label + "[1]");
  finite_float(value.z, label + "[2]");
  return value;
}

OptionalString clean_name(const OptionalString& name) {
  if (!name) return std::nullopt;
  std::string text = strip(*name);
  if (text.empty()) throw ValueError("name must not be empty when provided");
  return text;
}

std::string python_repr(std::string_view text) {
  const bool has_single = text.find('\'') != std::string_view::npos;
  const bool has_double = text.find('"') != std::string_view::npos;
  const char quote = has_single && !has_double ? '"' : '\'';
  std::string out(1, quote);
  for (const char c : text) {
    const auto byte = static_cast<unsigned char>(c);
    if (c == quote || c == '\\') {
      out += '\\';
      out += c;
    } else if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else if (byte < 0x20 || byte == 0x7f) {
      char buffer[8];
      std::snprintf(buffer, sizeof buffer, "\\x%02x", byte);
      out += buffer;
    } else {
      out += c;
    }
  }
  out += quote;
  return out;
}

std::string exception_text(const std::exception& error) {
  if (dynamic_cast<const reactive::KeyError*>(&error) != nullptr) return python_repr(error.what());
  return error.what();
}

Value to_array(const Vec3& v) { return Value(Value::Array{Value(v.x), Value(v.y), Value(v.z)}); }

}  // namespace scad::product
