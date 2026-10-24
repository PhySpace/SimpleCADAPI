// Value: a JSON-like dynamic value.
//
// The Python code base passes dicts, lists and scalars through shape metadata,
// tag evidence and recorded operation parameters.  Value is that, with
// insertion-ordered objects (Python dict order is observable in the editor and
// in canonical JSON).  Pybind11 converts it to and from native Python objects.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace scad {

class Value {
 public:
  using Array = std::vector<Value>;
  using Member = std::pair<std::string, Value>;
  using Object = std::vector<Member>;
  // An array that was a Python tuple.  It is an array in every respect (is_array, as_array,
  // equality, JSON); the distinction survives only for Python, where recorded parameters keep
  // the container type the caller used (it shows in a node's display summary).
  struct Tuple : Array {
    Tuple() = default;
    explicit Tuple(Array items) : Array(std::move(items)) {}
  };

  Value() = default;                                                     // null
  Value(std::nullptr_t) {}                                               // NOLINT
  Value(bool v) : data_(v) {}                                            // NOLINT
  Value(int v) : data_(static_cast<std::int64_t>(v)) {}                  // NOLINT
  Value(std::int64_t v) : data_(v) {}                                    // NOLINT
  Value(double v) : data_(v) {}                                          // NOLINT
  Value(const char* v) : data_(std::string(v)) {}                        // NOLINT
  Value(std::string v) : data_(std::move(v)) {}                          // NOLINT
  Value(std::string_view v) : data_(std::string(v)) {}                   // NOLINT
  Value(Array v) : data_(std::move(v)) {}                                // NOLINT
  Value(Object v) : data_(std::move(v)) {}                               // NOLINT

  Value(Tuple v) : data_(std::move(v)) {}                                // NOLINT

  static Value array() { return Value(Array{}); }
  static Value tuple(Array items = {}) { return Value(Tuple(std::move(items))); }
  static Value object() { return Value(Object{}); }

  bool is_null() const noexcept { return std::holds_alternative<std::monostate>(data_); }
  bool is_bool() const noexcept { return std::holds_alternative<bool>(data_); }
  bool is_int() const noexcept { return std::holds_alternative<std::int64_t>(data_); }
  bool is_double() const noexcept { return std::holds_alternative<double>(data_); }
  bool is_number() const noexcept { return is_int() || is_double(); }
  bool is_string() const noexcept { return std::holds_alternative<std::string>(data_); }
  bool is_array() const noexcept { return std::holds_alternative<Array>(data_) || is_tuple(); }
  bool is_tuple() const noexcept { return std::holds_alternative<Tuple>(data_); }
  bool is_object() const noexcept { return std::holds_alternative<Object>(data_); }

  // Checked accessors; throw scad::TypeError on a kind mismatch.
  bool as_bool() const;
  std::int64_t as_int() const;
  double as_double() const;  // accepts int too
  const std::string& as_string() const;
  const Array& as_array() const;
  Array& as_array();
  const Object& as_object() const;
  Object& as_object();

  // Object helpers.  `find` returns nullptr when absent or when this is not an object.
  const Value* find(std::string_view key) const noexcept;
  Value* find(std::string_view key) noexcept;
  // Insert or replace, keeping first-insertion position.  Turns null into an object.
  Value& set(std::string key, Value value);
  bool erase(std::string_view key);

  // Array helper; turns null into an array.
  Value& push_back(Value value);

  std::size_t size() const noexcept;  // elements / members; 0 for scalars

  bool operator==(const Value& other) const;
  bool operator!=(const Value& other) const { return !(*this == other); }

  // Compact JSON text (keys in insertion order, non-finite numbers as null).
  std::string dump() const;

 private:
  std::variant<std::monostate, bool, std::int64_t, double, std::string, Array, Object, Tuple> data_;
};

}  // namespace scad
