// Assembly constraints and the reports about them (product/constraint.py).
#pragma once

#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/product/connector.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

// A closed range for a constraint's drive coordinate (degrees for a revolute, length for a prismatic).
class ScalarLimit : public SemanticValue {
 public:
  // ValueError for a non-finite bound or lower > upper.
  ScalarLimit(double lower_value, double upper_value);

  double lower_value() const noexcept { return lower_; }
  double upper_value() const noexcept { return upper_; }
  bool contains(double value) const;

  Value to_dict() const;
  bool operator==(const ScalarLimit& other) const noexcept { return lower_ == other.lower_ && upper_ == other.upper_; }

 private:
  double lower_, upper_;
};

// The kinds a constraint can be, as its constraint_kind string says.
bool is_coupling_kind(const std::string& kind) noexcept;  // gear, belt, rack_pinion

// Everything a constraint can carry besides its id, kind and two connectors; which fields are
// allowed depends on the kind (the Constraint constructor says ValueError otherwise).
struct ConstraintSettings {
  OptionalDouble drive_distance;
  std::optional<ScalarLimit> distance_limit;
  OptionalDouble drive_angle_degrees;
  std::optional<ScalarLimit> angle_limit;
  OptionalDouble pitch_radius_a, pitch_radius_b;
  OptionalDouble pulley_radius_a, pulley_radius_b;
  OptionalDouble pitch_radius;
  OptionalDouble phase_offset;
  OptionalString name;
};

class Constraint : public SemanticValue {
 public:
  // `constraint_kind`: fixed, revolute, prismatic, gear, belt or rack_pinion.  Coupling kinds
  // default the phase offset to 0.
  Constraint(std::string constraint_id, std::string constraint_kind, ConnectorRef connector_a, ConnectorRef connector_b,
             ConstraintSettings settings = {});

  const std::string& constraint_id() const noexcept { return id_; }
  const std::string& constraint_kind() const noexcept { return kind_; }
  const ConnectorRef& connector_a() const noexcept { return a_; }
  const ConnectorRef& connector_b() const noexcept { return b_; }
  const ConstraintSettings& settings() const noexcept { return settings_; }

  const OptionalDouble& drive_distance() const noexcept { return settings_.drive_distance; }
  const std::optional<ScalarLimit>& distance_limit() const noexcept { return settings_.distance_limit; }
  const OptionalDouble& drive_angle_degrees() const noexcept { return settings_.drive_angle_degrees; }
  const std::optional<ScalarLimit>& angle_limit() const noexcept { return settings_.angle_limit; }
  const OptionalDouble& pitch_radius_a() const noexcept { return settings_.pitch_radius_a; }
  const OptionalDouble& pitch_radius_b() const noexcept { return settings_.pitch_radius_b; }
  const OptionalDouble& pulley_radius_a() const noexcept { return settings_.pulley_radius_a; }
  const OptionalDouble& pulley_radius_b() const noexcept { return settings_.pulley_radius_b; }
  const OptionalDouble& pitch_radius() const noexcept { return settings_.pitch_radius; }
  const OptionalDouble& phase_offset() const noexcept { return settings_.phase_offset; }
  const OptionalString& name() const noexcept { return settings_.name; }

  bool is_coupling() const noexcept { return is_coupling_kind(kind_); }

  Value to_dict() const;
  bool operator==(const Constraint& other) const;

 private:
  std::string id_, kind_;
  ConnectorRef a_, b_;
  ConstraintSettings settings_;
};

// How far one constraint is from holding.
struct ConstraintResidual {
  std::string constraint_id;
  double translation_error = 0.0;
  double angular_error_degrees = 0.0;
  bool within_tolerance = false;

  Value to_dict() const;
  bool operator==(const ConstraintResidual&) const = default;
};

struct ConstraintReport {
  bool solved = false;
  std::vector<std::string> grounded_component_ids;
  std::vector<std::string> solved_component_ids;
  std::vector<std::string> unsolved_component_ids;
  std::vector<ConstraintResidual> residuals;

  Value to_dict() const;
  bool operator==(const ConstraintReport&) const = default;
};

}  // namespace scad::product
