// A small builder for the metadata dictionaries the factories attach to their results.
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/value.hpp"

namespace scad::stdlib {

// Dict("a", 1)("b", 2.5).take(): insertion-ordered, like the Python dict literals.
class Dict {
 public:
  Dict() = default;
  Dict(std::string key, Value value) { v_.set(std::move(key), std::move(value)); }

  Dict& operator()(std::string key, Value value) {
    v_.set(std::move(key), std::move(value));
    return *this;
  }
  // Every member of `other`, after the ones already here (Python: {**other, ...}).
  Dict& merge(const Value& other) {
    for (const auto& [key, value] : other.as_object())
      v_.set(key, value);
    return *this;
  }
  Value take() { return std::move(v_); }

 private:
  Value v_ = Value::object();
};

inline Value number_or_null(const std::optional<double>& value) {
  return value ? Value(*value) : Value();
}

template <class T>
Value list_of(const std::vector<T>& items) {
  Value out = Value::array();
  for (const T& item : items)
    out.push_back(Value(item));
  return out;
}

}  // namespace scad::stdlib
