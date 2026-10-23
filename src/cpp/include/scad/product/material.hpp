// A material definition, assigned to a Part with assign_material_rpart.
#pragma once

#include <optional>
#include <string>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

class Material : public SemanticValue {
 public:
  // ValueError for a malformed id, an empty name, a density that is not positive, a density
  // without a unit (or a unit without a density), or a colour outside [0, 1].
  explicit Material(std::string material_id, OptionalString name = {}, OptionalDouble density = {},
                    OptionalString density_unit = {}, std::optional<Vec3> color = {});

  const std::string& material_id() const noexcept { return material_id_; }
  const OptionalString& name() const noexcept { return name_; }
  const OptionalDouble& density() const noexcept { return density_; }
  const OptionalString& density_unit() const noexcept { return density_unit_; }
  const std::optional<Vec3>& color() const noexcept { return color_; }

  Value to_dict() const;
  bool operator==(const Material& other) const noexcept;

 private:
  std::string material_id_;
  OptionalString name_;
  OptionalDouble density_;
  OptionalString density_unit_;
  std::optional<Vec3> color_;
};

}  // namespace scad::product
