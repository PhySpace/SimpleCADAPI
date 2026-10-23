#include "scad/product/constraint.hpp"

#include <algorithm>
#include <cctype>

#include "scad/core/error.hpp"

namespace scad::product {

// ---------------------------------------------------------------------------
// ScalarLimit
// ---------------------------------------------------------------------------

ScalarLimit::ScalarLimit(double lower_value, double upper_value)
    : lower_(finite_float(lower_value, "lower_value")), upper_(finite_float(upper_value, "upper_value")) {
  if (lower_ > upper_) throw ValueError("lower_value must be less than or equal to upper_value");
}

bool ScalarLimit::contains(double value) const {
  const double scalar = finite_float(value, "value");
  return lower_ <= scalar && scalar <= upper_;
}

Value ScalarLimit::to_dict() const {
  Value out = Value::object();
  out.set("lower_value", lower_);
  out.set("upper_value", upper_);
  return out;
}

// ---------------------------------------------------------------------------
// Constraint
// ---------------------------------------------------------------------------

bool is_coupling_kind(const std::string& kind) noexcept { return kind == "gear" || kind == "belt" || kind == "rack_pinion"; }

namespace {

std::string normalized_kind(const std::string& raw) {
  std::string kind = strip(raw);
  std::transform(kind.begin(), kind.end(), kind.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (kind != "fixed" && kind != "revolute" && kind != "prismatic" && kind != "gear" && kind != "belt" &&
      kind != "rack_pinion") {
    throw ValueError("constraint_kind must be fixed, revolute, prismatic, gear, belt, or rack_pinion");
  }
  return kind;
}

bool any_set(std::initializer_list<const OptionalDouble*> values) {
  return std::any_of(values.begin(), values.end(), [](const OptionalDouble* v) { return v->has_value(); });
}

// The kind-specific rules, in the order the Python constructor applies them.
void check_kind_rules(const std::string& kind, ConstraintSettings& s) {
  const bool has_limit = s.distance_limit || s.angle_limit;
  const bool has_drive = s.drive_distance || s.drive_angle_degrees;
  if ((kind == "fixed" || kind == "revolute" || kind == "prismatic") &&
      any_set({&s.pitch_radius_a, &s.pitch_radius_b, &s.pulley_radius_a, &s.pulley_radius_b, &s.pitch_radius,
               &s.phase_offset})) {
    throw ValueError(kind + " constraints do not accept coupling radii or phase_offset");
  }
  if (kind == "fixed") {
    if (has_drive) throw ValueError("fixed constraints do not accept drive scalars");
    if (has_limit) throw ValueError("fixed constraints do not accept scalar limits");
  }
  if (kind == "revolute" && (s.drive_distance || s.distance_limit)) {
    throw ValueError("revolute constraints only accept angle scalars");
  }
  if (kind == "prismatic" && (s.drive_angle_degrees || s.angle_limit)) {
    throw ValueError("prismatic constraints only accept distance scalars");
  }
  if (is_coupling_kind(kind)) {
    if (has_drive) throw ValueError(kind + " constraints do not accept drive scalars");
    if (has_limit) throw ValueError(kind + " constraints do not accept scalar limits");
    if (!s.phase_offset) s.phase_offset = 0.0;
  }
  if (kind == "gear") {
    if (!s.pitch_radius_a || !s.pitch_radius_b) throw ValueError("gear constraints require pitch_radius_a and pitch_radius_b");
    if (any_set({&s.pulley_radius_a, &s.pulley_radius_b, &s.pitch_radius})) {
      throw ValueError("gear constraints only accept pitch_radius_a and pitch_radius_b");
    }
  }
  if (kind == "belt") {
    if (!s.pulley_radius_a || !s.pulley_radius_b) throw ValueError("belt constraints require pulley_radius_a and pulley_radius_b");
    if (any_set({&s.pitch_radius_a, &s.pitch_radius_b, &s.pitch_radius})) {
      throw ValueError("belt constraints only accept pulley_radius_a and pulley_radius_b");
    }
  }
  if (kind == "rack_pinion") {
    if (!s.pitch_radius) throw ValueError("rack_pinion constraints require pitch_radius");
    if (any_set({&s.pitch_radius_a, &s.pitch_radius_b, &s.pulley_radius_a, &s.pulley_radius_b})) {
      throw ValueError("rack_pinion constraints only accept pitch_radius");
    }
  }
}

}  // namespace

Constraint::Constraint(std::string constraint_id, std::string constraint_kind, ConnectorRef connector_a,
                       ConnectorRef connector_b, ConstraintSettings settings)
    : id_(validate_identifier(constraint_id, "constraint_id")),
      kind_(normalized_kind(constraint_kind)),
      a_(std::move(connector_a)),
      b_(std::move(connector_b)),
      settings_(std::move(settings)) {
  if (a_ == b_) throw ValueError("constraint cannot connect the same connector ref twice");
  ConstraintSettings& s = settings_;
  optional_float(s.drive_distance, "drive_distance");
  optional_float(s.drive_angle_degrees, "drive_angle_degrees");
  optional_positive_float(s.pitch_radius_a, "pitch_radius_a");
  optional_positive_float(s.pitch_radius_b, "pitch_radius_b");
  optional_positive_float(s.pulley_radius_a, "pulley_radius_a");
  optional_positive_float(s.pulley_radius_b, "pulley_radius_b");
  optional_positive_float(s.pitch_radius, "pitch_radius");
  optional_float(s.phase_offset, "phase_offset");
  check_kind_rules(kind_, s);
  s.name = clean_name(s.name);
}

namespace {

Value optional_value(const OptionalDouble& value) { return value ? Value(*value) : Value(); }
Value limit_value(const std::optional<ScalarLimit>& limit) { return limit ? limit->to_dict() : Value(); }

}  // namespace

Value Constraint::to_dict() const {
  const ConstraintSettings& s = settings_;
  Value out = Value::object();
  out.set("constraint_id", id_);
  out.set("constraint_kind", kind_);
  out.set("connector_a", a_.to_dict());
  out.set("connector_b", b_.to_dict());
  out.set("drive_distance", optional_value(s.drive_distance));
  out.set("distance_limit", limit_value(s.distance_limit));
  out.set("drive_angle_degrees", optional_value(s.drive_angle_degrees));
  out.set("angle_limit", limit_value(s.angle_limit));
  out.set("pitch_radius_a", optional_value(s.pitch_radius_a));
  out.set("pitch_radius_b", optional_value(s.pitch_radius_b));
  out.set("pulley_radius_a", optional_value(s.pulley_radius_a));
  out.set("pulley_radius_b", optional_value(s.pulley_radius_b));
  out.set("pitch_radius", optional_value(s.pitch_radius));
  out.set("phase_offset", optional_value(s.phase_offset));
  out.set("name", s.name ? Value(*s.name) : Value());
  return out;
}

bool Constraint::operator==(const Constraint& other) const {
  const ConstraintSettings& s = settings_;
  const ConstraintSettings& o = other.settings_;
  return id_ == other.id_ && kind_ == other.kind_ && a_ == other.a_ && b_ == other.b_ &&
         s.drive_distance == o.drive_distance && s.distance_limit == o.distance_limit &&
         s.drive_angle_degrees == o.drive_angle_degrees && s.angle_limit == o.angle_limit &&
         s.pitch_radius_a == o.pitch_radius_a && s.pitch_radius_b == o.pitch_radius_b &&
         s.pulley_radius_a == o.pulley_radius_a && s.pulley_radius_b == o.pulley_radius_b &&
         s.pitch_radius == o.pitch_radius && s.phase_offset == o.phase_offset && s.name == o.name;
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

Value ConstraintResidual::to_dict() const {
  Value out = Value::object();
  out.set("constraint_id", constraint_id);
  out.set("translation_error", translation_error);
  out.set("angular_error_degrees", angular_error_degrees);
  out.set("within_tolerance", within_tolerance);
  return out;
}

namespace {

Value string_array(const std::vector<std::string>& items) {
  Value out = Value::array();
  for (const std::string& item : items) out.push_back(item);
  return out;
}

}  // namespace

Value ConstraintReport::to_dict() const {
  Value out = Value::object();
  out.set("solved", solved);
  out.set("grounded_component_ids", string_array(grounded_component_ids));
  out.set("solved_component_ids", string_array(solved_component_ids));
  out.set("unsolved_component_ids", string_array(unsolved_component_ids));
  Value rows = Value::array();
  for (const ConstraintResidual& residual : residuals) rows.push_back(residual.to_dict());
  out.set("residuals", std::move(rows));
  return out;
}

}  // namespace scad::product
