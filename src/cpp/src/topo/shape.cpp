#include <functional>
#include <algorithm>

#include "internal.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"

namespace scad {

Shape::~Shape() = default;

Shape::Shape(TopoDS_Shape occurrence, std::shared_ptr<Entity> entity, std::shared_ptr<Registry> registry) noexcept
    : shape_(std::move(occurrence)), entity_(std::move(entity)), registry_(std::move(registry)) {}

Shape::Shape(const TopoDS_Shape& shape, Kind expected) {
  const Kind actual = kind_of(shape);
  if (actual != expected) {
    throw TypeError(std::string("expected a ") + std::string(kind_name(expected)) + ", got a " +
                    std::string(kind_name(actual)));
  }
  shape_ = shape;
  registry_ = std::make_shared<Registry>(shape);
  entity_ = registry_->acquire(expected, shape);
}

Shape Shape::from_occt(const TopoDS_Shape& shape) {
  const Kind kind = kind_of(shape);
  auto registry = std::make_shared<Registry>(shape);
  auto entity = registry->acquire(kind, shape);
  return Shape(shape, std::move(entity), std::move(registry));
}

Shape Shape::sub(const TopoDS_Shape& shape) const {
  const Kind kind = kind_of(shape);
  return Shape(shape, registry_->acquire(kind, shape), registry_);
}

Shape Shape::child(const TopoDS_Shape& shape, Kind kind) const {
  auto entity = registry_->acquire(kind, shape);
  const bool known = std::any_of(entity->parents.begin(), entity->parents.end(),
                                 [&](const auto& weak) { return weak.lock() == entity_; });
  if (!known)
    entity->parents.push_back(entity_);
  return Shape(shape, std::move(entity), registry_);
}

Shape Shape::ancestor(const TopoDS_Shape& shape, Kind kind) const {
  auto entity = registry_->acquire(kind, shape);
  const bool known = std::any_of(entity_->parents.begin(), entity_->parents.end(),
                                 [&](const auto& weak) { return weak.lock() == entity; });
  if (!known)
    entity_->parents.push_back(entity);
  return Shape(shape, std::move(entity), registry_);
}

Kind Shape::kind() const noexcept {
  return entity_->kind;
}
const std::string& Shape::topo_id() const noexcept {
  return entity_->topo_id.str();
}

bool Shape::is_same(const Shape& other) const noexcept {
  return shape_.IsSame(other.shape_);
}
bool Shape::same_entity(const Shape& other) const noexcept {
  return registry_ == other.registry_ && entity_ == other.entity_;
}

void Shape::set_graph_node(std::shared_ptr<const void> node) const {
  entity_->state().graph_node = std::move(node);
}
std::shared_ptr<const void> Shape::graph_node() const {
  const SemanticState* state = entity_->state_if();
  return state != nullptr ? state->graph_node : nullptr;
}

std::size_t Shape::entity_key() const noexcept {
  return std::hash<const void*>{}(entity_.get()) * 31u + std::hash<const void*>{}(registry_.get());
}

// Shape::clone_view lives with the rest of the semantic state, in shape_tags.cpp.

std::vector<Shape> Shape::known_parents() const {
  std::vector<Shape> out;
  for (const auto& weak : entity_->parents) {
    if (auto parent = weak.lock()) {
      // Read the occurrence first: argument evaluation order is unspecified, and GCC moves
      // `parent` into its parameter before it evaluates `parent->shape`.
      TopoDS_Shape occurrence = parent->shape;
      out.push_back(Shape(std::move(occurrence), std::move(parent), registry_));
    }
  }
  return out;
}

Vec3 Shape::center() const {
  return kernel::center_of_mass(shape_);
}
kernel::BoundingBox Shape::bounding_box() const {
  return kernel::bounding_box(shape_);
}

}  // namespace scad
