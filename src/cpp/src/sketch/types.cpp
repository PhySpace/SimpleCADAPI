#include "scad/sketch/types.hpp"

#include <cmath>
#include <sstream>

#include "scad/core/error.hpp"

namespace scad {

namespace {

Value point_value(const SketchPoint2& point) {
  return Value(Value::Array{Value(point.first), Value(point.second)});
}

std::string quoted(const std::string& text) {
  return "'" + text + "'";
}

}  // namespace

double as_float(const Scalar& scalar) {
  return evaluate_scalar(scalar, "value");
}

// ---- SketchRef ------------------------------------------------------------
Value SketchRef::to_value() const {
  Value out = Value::object();
  out.set("sketch_id", sketch_id);
  out.set("entity_id", entity_id);
  out.set("kind", kind);
  out.set("subentity", subentity);
  return out;
}

SketchRef SketchRef::from_value(const Value& data) {
  const auto field = [&data](const char* key) -> const Value& {
    const Value* value = data.find(key);
    if (value == nullptr)
      throw Exception(PyKind::KeyError, std::string("'") + key + "'");
    return *value;
  };
  SketchRef ref;
  ref.sketch_id = field("sketch_id").as_string();
  ref.entity_id = field("entity_id").as_string();
  ref.kind = field("kind").as_string();
  if (const Value* sub = data.find("subentity"))
    ref.subentity = sub->as_string();
  return ref;
}

std::string SketchRef::repr() const {
  return "SketchRef(sketch_id=" + quoted(sketch_id) + ", entity_id=" + quoted(entity_id) + ", kind=" + quoted(kind) +
         ", subentity=" + quoted(subentity) + ")";
}

// ---- SketchEntity ---------------------------------------------------------
const std::string& SketchEntity::point_id(std::string_view role) const {
  const Value* value = data.find(role);
  if (value == nullptr) {
    throw Exception(PyKind::KeyError, "'" + std::string(role) + "' (sketch entity '" + id + "')");
  }
  return value->as_string();
}

double SketchEntity::number(std::string_view key) const {
  if (const auto it = scalars.find(key); it != scalars.end()) {
    return evaluate_scalar(it->second, std::string(key));
  }
  const Value* value = data.find(key);
  if (value == nullptr) {
    throw Exception(PyKind::KeyError, "'" + std::string(key) + "' (sketch entity '" + id + "')");
  }
  return value->as_double();
}

SketchBSpline SketchEntity::bspline() const {
  SketchBSpline spline;
  spline.degree = static_cast<int>(data.find("degree")->as_int());
  for (const Value& pole : data.find("control_points")->as_array()) {
    SketchPole out;
    if (pole.is_object()) {
      const Value* point = pole.find("point_id");
      if (point == nullptr)
        point = pole.find("point");
      if (point == nullptr)
        throw ValueError("B-spline control-point mapping requires point_id");
      out.point_id = point->as_string();
    } else {
      const auto& xy = pole.as_array();
      out.x = xy.at(0).as_double();
      out.y = xy.at(1).as_double();
    }
    spline.poles.push_back(std::move(out));
  }
  for (const Value& knot : data.find("knots")->as_array())
    spline.knots.push_back(knot.as_double());
  for (const Value& mult : data.find("multiplicities")->as_array()) {
    spline.multiplicities.push_back(static_cast<int>(mult.as_int()));
  }
  if (const Value* weights = data.find("weights"); weights != nullptr && !weights->is_null()) {
    std::vector<double> values;
    for (const Value& weight : weights->as_array())
      values.push_back(weight.as_double());
    spline.weights = std::move(values);
  }
  if (const Value* periodic = data.find("periodic"))
    spline.periodic = periodic->as_bool();
  return spline;
}

Value SketchEntity::to_value() const {
  Value out = Value::object();
  out.set("id", id);
  out.set("kind", kind);
  out.set("construction", construction);
  for (const auto& [key, value] : data.as_object())
    out.set(key, value);
  return out;
}

// ---- SketchConstraint -----------------------------------------------------
double SketchConstraint::numeric_value() const {
  if (!value)
    throw ValueError("Sketch constraint '" + id + "' has no value");
  return evaluate_scalar(*value, "value");
}

Value SketchConstraint::to_value() const {
  Value out = Value::object();
  out.set("id", id);
  out.set("kind", kind);
  Value::Array target_values;
  for (const SketchRef& target : targets)
    target_values.push_back(target.to_value());
  out.set("targets", Value(std::move(target_values)));
  out.set("driving", driving);
  if (value)
    out.set("value", Value(evaluate_scalar(*value, "value")));
  if (metadata.size() > 0)
    out.set("metadata", metadata);
  return out;
}

// ---- diagnostics and results ----------------------------------------------
Value SketchConstraintDiagnostic::to_value() const {
  Value out = Value::object();
  out.set("constraint_id", constraint_id ? Value(*constraint_id) : Value());
  out.set("severity", severity);
  out.set("code", code);
  out.set("message", message);
  out.set("residual", residual ? Value(*residual) : Value());
  return out;
}

Value SketchSolveResult::to_value() const {
  Value out = Value::object();
  out.set("sketch_id", sketch_id);
  out.set("status", status);
  out.set("dof", dof);
  out.set("residual_norm", residual_norm);
  out.set("iterations", iterations);
  Value points = Value::object();
  for (const auto& [key, point] : solved_points)
    points.set(key, point_value(point));
  out.set("solved_points", std::move(points));
  Value scalars = Value::object();
  for (const auto& [key, number] : solved_scalars)
    scalars.set(key, number);
  out.set("solved_scalars", std::move(scalars));
  Value entities = Value::object();
  for (const auto& [key, entity] : solved_entities)
    entities.set(key, entity);
  out.set("solved_entities", std::move(entities));
  Value::Array diagnostic_values;
  for (const auto& diagnostic : diagnostics)
    diagnostic_values.push_back(diagnostic.to_value());
  out.set("diagnostics", Value(std::move(diagnostic_values)));
  out.set("backend", backend);
  out.set("backend_version", backend_version);
  out.set("backend_status_code", backend_status_code ? Value(*backend_status_code) : Value());
  return out;
}

}  // namespace scad
