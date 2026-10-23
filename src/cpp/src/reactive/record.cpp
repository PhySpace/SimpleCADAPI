#include "scad/reactive/record.hpp"

#include "scad/reactive/param_path.hpp"

namespace scad::reactive {

OperationBuilder::OperationBuilder(std::string op) : recorder_(current_recorder()) {
  if (recorder_ != nullptr) {
    record_.op = std::move(op);
    record_.params = Value::object();
  }
}

double OperationBuilder::scalar(std::string_view name, const Scalar& value) {
  const double number = evaluate_scalar(value, name);
  if (recorder_ != nullptr) {
    record_.params.set(std::string(name), number);
    if (value.symbolic()) record_.symbolic.emplace_back(std::string(name), value);
  }
  return number;
}

double OperationBuilder::scalar_at(std::string_view name, std::size_t index, const Scalar& value) {
  const std::string path = std::string(name) + "[" + std::to_string(index) + "]";
  const double number = evaluate_scalar(value, path);
  if (recorder_ != nullptr) {
    set_param(record_.params, ParamPath::parse(path), Value(number));
    if (value.symbolic()) record_.symbolic.emplace_back(path, value);
  }
  return number;
}

OperationBuilder& OperationBuilder::param(std::string_view name, Value value) {
  if (recorder_ != nullptr) record_.params.set(std::string(name), std::move(value));
  return *this;
}

OperationBuilder& OperationBuilder::input(const Shape& shape, std::string role) {
  if (recorder_ != nullptr) record_.inputs.push_back(OpInput{shape, std::move(role)});
  return *this;
}

OperationBuilder& OperationBuilder::delta(TopoDelta delta) {
  if (recorder_ != nullptr) record_.delta = std::move(delta);
  return *this;
}

OperationBuilder& OperationBuilder::semantic_delta(SemanticDelta delta) {
  if (recorder_ != nullptr) record_.semantic_delta = std::move(delta);
  return *this;
}

void OperationBuilder::record(const std::vector<Shape>& outputs) const {
  if (recorder_ != nullptr) recorder_->record(record_, outputs);
}

}  // namespace scad::reactive
