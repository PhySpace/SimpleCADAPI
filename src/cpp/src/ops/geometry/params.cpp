#include "scad/ops/geometry/params.hpp"

#include <algorithm>

namespace scad {

namespace {

std::string indexed(const std::string& path, std::size_t index) {
  return path + "[" + std::to_string(index) + "]";
}

}  // namespace

OpParams::OpParams(std::string op, std::vector<std::string> labels) {
  record_.op = std::move(op);
  record_.params = Value::object();
  record_.labels = std::move(labels);
}

OpParams& OpParams::scalar(std::string_view name, const Scalar& value) {
  const std::string path(name);
  record_.params.set(path, Value(evaluate_scalar(value, path)));
  if (value.symbolic())
    record_.symbolic.emplace_back(path, value);
  return *this;
}

namespace {

// One coordinate list of a parameter: numbers go into `out`, symbolic ones are noted under `path[i]`.
template <class Coordinates>
Value coordinate_array(const Coordinates& coordinates, const std::string& path, OpRecord& record, bool tuple = true) {
  Value::Array items;
  for (std::size_t i = 0; i < coordinates.size(); ++i) {
    const std::string item = indexed(path, i);
    items.push_back(Value(evaluate_scalar(coordinates[i], item)));
    if (coordinates[i].symbolic())
      record.symbolic.emplace_back(item, coordinates[i]);
  }
  return tuple ? Value::tuple(std::move(items)) : Value(std::move(items));
}

}  // namespace

OpParams& OpParams::point(std::string_view name, const Scalar3& value) {
  record_.params.set(std::string(name), coordinate_array(value, std::string(name), record_));
  return *this;
}

OpParams& OpParams::optional_point(std::string_view name, const std::optional<Scalar3>& value) {
  return value ? point(name, *value) : null(name);
}

OpParams& OpParams::points(std::string_view name, const std::vector<Scalar3>& value) {
  Value out = Value::array();
  for (std::size_t i = 0; i < value.size(); ++i)
    out.push_back(coordinate_array(value[i], indexed(std::string(name), i), record_));
  record_.params.set(std::string(name), std::move(out));
  return *this;
}

OpParams& OpParams::coordinates(std::string_view name, const std::vector<ScalarPoint>& value) {
  Value out = Value::array();
  for (std::size_t i = 0; i < value.size(); ++i)
    out.push_back(coordinate_array(value[i], indexed(std::string(name), i), record_));
  record_.params.set(std::string(name), std::move(out));
  return *this;
}

OpParams& OpParams::scalars(std::string_view name, const ScalarList& value) {
  record_.params.set(std::string(name), coordinate_array(value, std::string(name), record_, /*tuple=*/false));
  return *this;
}

OpParams& OpParams::optional_scalars(std::string_view name, const std::optional<ScalarList>& value) {
  return value ? scalars(name, *value) : null(name);
}

OpParams& OpParams::vec(std::string_view name, const Vec3& value) {
  record_.params.set(std::string(name), Value::tuple({Value(value.x), Value(value.y), Value(value.z)}));
  return *this;
}

OpParams& OpParams::numbers(std::string_view name, const std::vector<double>& value) {
  Value out = Value::array();
  for (const double number : value)
    out.push_back(Value(number));
  record_.params.set(std::string(name), std::move(out));
  return *this;
}

OpParams& OpParams::integers(std::string_view name, const std::vector<int>& value) {
  Value out = Value::array();
  for (const int number : value)
    out.push_back(Value(number));
  record_.params.set(std::string(name), std::move(out));
  return *this;
}

OpParams& OpParams::integer(std::string_view name, std::int64_t value) {
  record_.params.set(std::string(name), Value(value));
  return *this;
}

OpParams& OpParams::boolean(std::string_view name, bool value) {
  record_.params.set(std::string(name), Value(value));
  return *this;
}

OpParams& OpParams::text(std::string_view name, std::string_view value) {
  record_.params.set(std::string(name), Value(value));
  return *this;
}

OpParams& OpParams::optional_text(std::string_view name, const OptionalString& value) {
  return value ? text(name, *value) : null(name);
}

OpParams& OpParams::null(std::string_view name) {
  record_.params.set(std::string(name), Value());
  return *this;
}

OpParams& OpParams::input(Shape shape, std::string role) {
  record_.inputs.push_back(OpInput{std::move(shape), std::move(role)});
  return *this;
}

OpRecord OpParams::take() {
  return std::move(record_);
}

namespace {

// Python passes these as a set; the recorder sees them in sorted order.
std::vector<std::string> sorted_labels(std::string_view role, std::string_view kind) {
  std::vector<std::string> labels{std::string(role), std::string(kind)};
  std::sort(labels.begin(), labels.end());
  return labels;
}

}  // namespace

std::vector<std::string> primitive_labels(std::string_view kind) {
  return sorted_labels("primitive", kind);
}
std::vector<std::string> derived_labels(std::string_view kind) {
  return sorted_labels("derived", kind);
}

}  // namespace scad
