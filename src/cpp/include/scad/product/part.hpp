// A Part: one Solid (its body), with an optional material and its connector datums (product/part.py).  Values are
// immutable: every `with_*` returns a new Part.
//
// A Part holds exactly one solid: it is the unit an assembly places, mates and gives connectors to.  Several solids
// that exist side by side while a model is built (a tool and its target) are loose values of the notebook, and a
// deliverable of several solids is an Assembly of Parts.  The body is kept as a `Body` only because it carries the
// display name, colour and opacity (`set_body_appearance_rpart`).
#pragma once

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/product/connector.hpp"
#include "scad/product/material.hpp"
#include "scad/product/semantic_value.hpp"
#include "scad/product/validation.hpp"
#include "scad/topo/shape.hpp"

namespace scad::product {

// One named solid of a Part.  The body id is a stable identifier within its Part ("base", "lid").
//
// A body may carry a display colour (RGB in [0, 1], like Material::color) and an opacity in [0, 1].  They are an
// appearance only: the material colour is the default, a body colour overrides it for display (preview, package
// scene, STEP surface colour).  Mass and density never read them.
class Body {
 public:
  // ValueError for a malformed id, an empty name, a colour outside [0, 1] or an opacity outside [0, 1].
  Body(std::string body_id, Solid solid, OptionalString name = {}, std::optional<Vec3> color = {},
       OptionalDouble opacity = {});

  const std::string& body_id() const noexcept { return body_id_; }
  const Solid& solid() const noexcept { return solid_; }
  const OptionalString& name() const noexcept { return name_; }
  const std::optional<Vec3>& color() const noexcept { return color_; }
  const OptionalDouble& opacity() const noexcept { return opacity_; }
  // True when the body has a colour or an opacity of its own.
  bool has_appearance() const noexcept { return color_.has_value() || opacity_.has_value(); }

  // A copy with another display name, colour and opacity (same id and solid).
  Body with_appearance(OptionalString name, std::optional<Vec3> color, OptionalDouble opacity) const;

  // {"body_id", "name"}, plus "color" / "opacity" when set (the solid is geometry, not a dict field).
  Value to_dict() const;

 private:
  std::string body_id_;
  Solid solid_;
  OptionalString name_;
  std::optional<Vec3> color_;
  OptionalDouble opacity_;
};

// The body id of a Part made from one Solid.
inline constexpr const char* kDefaultBodyId = "body";

class Part : public SemanticValue {
 public:
  // ValueError for a malformed id, an empty name, or duplicate connector ids.
  Part(std::string part_id, Solid body, OptionalString name = {}, std::optional<Material> material = {},
       std::vector<Connector> connectors = {});
  // A Part of the one body in `bodies` (a vector so that the body keeps its id and appearance).  ValueError for any
  // other number of bodies.
  Part(std::string part_id, std::vector<Body> bodies, OptionalString name = {}, std::optional<Material> material = {},
       std::vector<Connector> connectors = {});

  const std::string& part_id() const noexcept { return part_id_; }
  const Solid& body() const;
  // Always one element.
  const std::vector<Body>& bodies() const noexcept { return bodies_; }
  std::vector<std::string> body_ids() const;
  // KeyError ("part has no body_id 'x'") for an unknown id.
  const Body& get_body(std::string_view body_id) const;
  const OptionalString& name() const noexcept { return name_; }
  const std::optional<Material>& material() const noexcept { return material_; }
  const std::vector<Connector>& connectors() const noexcept { return connectors_; }

  Part with_material(const Material& material) const;
  // The Part with `body` in place of the body of the same id.  KeyError for an unknown id.
  Part with_body(const Body& body) const;
  // ValueError when the Part already has a connector with that id.
  Part with_connector(const Connector& connector) const;

  std::vector<std::string> connector_ids() const;
  // KeyError ("part has no connector_id 'x'") for an unknown id.
  const Connector& get_connector(std::string_view connector_id) const;

  Value to_dict() const;

 private:
  std::string part_id_;
  std::vector<Body> bodies_;
  OptionalString name_;
  std::optional<Material> material_;
  std::vector<Connector> connectors_;
};

using PartPtr = std::shared_ptr<const Part>;

}  // namespace scad::product
