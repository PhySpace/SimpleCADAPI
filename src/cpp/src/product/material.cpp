#include "scad/product/material.hpp"

#include "scad/core/error.hpp"

namespace scad::product {

Material::Material(std::string material_id, OptionalString name, OptionalDouble density, OptionalString density_unit,
                   std::optional<Vec3> color)
    : material_id_(validate_identifier(material_id, "material_id")), name_(clean_name(name)) {
  if (density) {
    density_ = finite_float(*density, "density");
    if (*density_ <= 0.0)
      throw ValueError("density must be positive when provided");
    if (!density_unit || strip(*density_unit).empty()) {
      throw ValueError("density_unit must be explicit when density is provided");
    }
    density_unit_ = strip(*density_unit);
  } else if (density_unit) {
    throw ValueError("density_unit requires density");
  }
  if (color) {
    const Vec3 rgb = finite_vec3(*color, "color");
    for (const double component : {rgb.x, rgb.y, rgb.z}) {
      if (component < 0.0 || component > 1.0)
        throw ValueError("color components must be in [0.0, 1.0]");
    }
    color_ = rgb;
  }
}

Value Material::to_dict() const {
  Value out = Value::object();
  out.set("material_id", material_id_);
  out.set("name", name_ ? Value(*name_) : Value());
  out.set("density", density_ ? Value(*density_) : Value());
  out.set("density_unit", density_unit_ ? Value(*density_unit_) : Value());
  out.set("color", color_ ? to_array(*color_) : Value());
  return out;
}

bool Material::operator==(const Material& other) const noexcept {
  return material_id_ == other.material_id_ && name_ == other.name_ && density_ == other.density_ &&
         density_unit_ == other.density_unit_ && color_ == other.color_;
}

}  // namespace scad::product
