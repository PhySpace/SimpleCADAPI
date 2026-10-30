// The shape model: Vertex, Edge, Wire, Face, Shell, Solid, Compound.
//
// Each is a cheap value handle (two shared_ptrs) over a TopoDS_Shape plus the
// *semantic state* the SDK hangs on topology: tags, tag bindings, lineage,
// metadata.  Handles obtained from the same root -- a face of a solid, asked
// for twice -- share one Entity, so a tag set through one is seen through the
// other, exactly like the wrapper objects in the Python SDK.
//
// What differs from the Python SDK is cost.  Python builds the whole
// Solid -> Face -> Wire -> Edge -> Vertex wrapper tree eagerly whenever a
// shape is constructed.  Here nothing below the handle exists until it is
// asked for: constructing a Solid is O(1), and enumerating faces creates
// entities for faces only.
//
// Threading: a Shape and everything reachable from it share mutable state and
// are not thread-safe.  Give each thread its own shapes (or copy via
// Shape::clone_view); the kernel calls themselves release no locks.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/topo/tagging.hpp"

namespace scad {

enum class Kind : std::uint8_t { Vertex, Edge, Wire, Face, Shell, Solid, Compound };

std::string_view kind_name(Kind kind) noexcept;  // "vertex", "edge", ...
Kind kind_of(const TopoDS_Shape& shape);         // ValueError for compsolid / unspecified

struct Entity;
class Registry;
class SemanticState;

class Vertex;
class Edge;
class Wire;
class Face;
class Shell;
class Solid;
class Compound;

class Shape {
 public:
  Shape(const Shape&) = default;
  Shape(Shape&&) noexcept = default;
  Shape& operator=(const Shape&) = default;
  Shape& operator=(Shape&&) noexcept = default;
  ~Shape();

  // A new root over `shape`; the kind is read from the shape.
  static Shape from_occt(const TopoDS_Shape& shape);

  // A handle on `shape`, a sub-shape of (or the same as) this handle's root,
  // sharing this handle's entity table.  This is how operators reach the
  // semantic state of an input's faces while walking an OCCT history.
  Shape sub(const TopoDS_Shape& shape) const;

  // ---- identity ---------------------------------------------------------
  Kind kind() const noexcept;
  const TopoDS_Shape& wrapped() const noexcept { return shape_; }
  // "face_3": stable for a given root.  Never compare ids across roots.
  const std::string& topo_id() const noexcept;
  // Same underlying topology (TopoDS_Shape::IsSame), regardless of root.
  bool is_same(const Shape& other) const noexcept;
  // Same entity: same root and same topology.
  bool same_entity(const Shape& other) const noexcept;
  // The graph node that produced this output, as an opaque pointer (the reactive layer knows its type).
  void set_graph_node(std::shared_ptr<const void> node) const;
  std::shared_ptr<const void> graph_node() const;
  // A key equal for exactly the handles for which same_entity holds (the hash of a handle).
  std::size_t entity_key() const noexcept;
  // How many writes to semantic state (tags, bindings, lineage, metadata) the entities of this handle's root have had.
  // Equal numbers before and after mean nobody changed the shape in between.
  std::uint64_t semantic_revision() const noexcept;

  template <class T>
  T as() const {
    return T(*this);
  }

  // ---- tags (TaggedMixin) -----------------------------------------------
  // add_tag: an internal annotation.  apply_tag: an annotation that can also
  // be passed down to sub-shapes when `propagate` is true (Python: _apply_tag,
  // whose default is to stay local).
  void add_tag(std::string_view tag);
  void apply_tag(std::string_view tag, bool propagate = false);
  // Remove the user-operation bindings of `tag` held by this entity (_remove_tag);
  // only the local scope is removable.  See remove_tag_bindings for other producers.
  bool remove_tag(std::string_view tag, TagScope scope = TagScope::Local);
  // `tag` is compared as given: a name that is not normalized is simply absent.
  // Throws UnsupportedQueryCapabilityError for the same scopes list_tag_bindings does.
  bool has_tag(std::string_view tag, TagScope scope = TagScope::Effective) const;
  // Local binding present, whatever the entity's legacy state (internal enumeration uses this).
  bool has_stored_tag(std::string_view tag) const;
  // Sorted, unique.
  std::vector<std::string> list_tags(TagScope scope = TagScope::Effective) const;
  // One record per visible binding of `tag`, in the layout of TaggedMixin._explain_tag:
  // {scope, binding_id, producer, attachment, binding[, topology_path][, lineage]}.
  std::vector<Value> explain_tag(std::string_view tag, TagScope scope = TagScope::Effective) const;

  // The canonical records: every binding this entity stores (local and legacy snapshots).
  // Mutators keep the tag-name caches in step.
  const std::vector<TagBinding>& local_bindings() const;
  void add_binding(TagBinding binding);
  const std::vector<TagLineageWitness>& lineage_witnesses() const;
  // Skipped when the same (binding, derivation, source, target) witness is already stored.
  void add_lineage_witness(TagLineageWitness witness);

  // ---- the rest of TaggedMixin ---------------------------------------------
  // _list_tag_bindings.  Throws UnsupportedQueryCapabilityError for any scope but
  // effective on an entity holding legacy snapshots, and for the lineage scope
  // unless the entity's lineage coverage is complete.
  std::vector<TagBinding> list_tag_bindings(TagScope scope = TagScope::Effective) const;
  std::vector<TagBinding> local_tag_bindings() const;  // attachment == local
  std::vector<TagBinding> legacy_effective_bindings() const;
  std::vector<InheritedTagBinding> inherited_tag_bindings_with_paths() const;
  std::vector<TagBinding> inherited_tag_bindings() const;
  std::vector<TagBinding> lineage_tag_bindings() const;
  // _add_tag_lineage: the witness targets this shape's topo id.
  void add_tag_lineage(const TagBinding& binding, LineageDerivation derivation, std::string_view source_topo_id,
                       TagEvidence evidence, std::string_view coverage = "complete");
  // _remove_tag(tag, matching_producer): returns how many bindings went.
  std::size_t remove_tag_bindings(std::string_view tag, TagProducerKind matching = TagProducerKind::UserOperation);
  std::size_t remove_tag_bindings(std::string_view tag, const TagProducer& matching);
  bool remove_tag_binding(std::string_view binding_id);
  // _replace_local_tag_bindings: keep the non-local bindings, swap in `bindings`.
  void replace_local_tag_bindings(std::vector<TagBinding> bindings);
  // `_tags = {...}`: replace every binding with legacy flat-token snapshots.
  void set_legacy_tags(const std::vector<std::string>& tags);
  // _refresh_tag_cache: rebuild this entity's tag-name caches from its bindings.
  // Inherited names are never cached, so `recursive` has nothing to refresh below.
  void refresh_tag_cache(bool recursive = false);

  void set_metadata(std::string key, Value value);
  Value get_metadata(std::string_view key, Value fallback = {}) const;
  const Value& metadata() const;
  // set_metadata / set_runtime, but the value is stored packed and expanded the first time the
  // dictionary is read (metadata(), get_metadata, ...), at the position it would have had.  For
  // bulky evidence nobody reads on the hot path (the "track" payload of every face and edge).
  bool has_metadata_key(std::string_view key) const;
  void set_metadata_deferred(std::string_view key, const Value& value);
  void set_runtime_deferred(std::string_view key, const Value& value);
  // Same, for a value that is a registered recipe (PackedValue::register_recipe) applied to `args`.
  void set_metadata_recipe(std::string_view key, unsigned char recipe, const Value& args);
  void set_runtime(std::string key, Value value);
  Value get_runtime(std::string_view key, Value fallback = {}) const;
  const Value& runtime() const;  // the whole runtime dictionary (an empty object when unset)

  // Replace this entity's tags / full semantic state with a copy of `source`'s.
  void copy_tag_state_from(const Shape& source);
  void copy_semantic_state_from(const Shape& source);

  // A detached view: same TopoDS_Shape, a new root, semantic state copied.
  // (clone_semantic_shape_view)
  Shape clone_view() const;
  // How many views clone_view has made in this process: what the SDK's tests learn by patching the Python helper
  // (apply_tag marks the shape itself; apply_tag_rselection works on a clone).
  static std::size_t clone_view_count() noexcept;

  // ---- measurements -----------------------------------------------------
  Vec3 center() const;
  kernel::BoundingBox bounding_box() const;

  // ---- structure --------------------------------------------------------
  // The containment parents seen so far (a Wire's Face, ...).  Only links that
  // enumeration has already established are returned.
  std::vector<Shape> known_parents() const;

  // ---- text -------------------------------------------------------------
  std::string repr() const;
  std::string to_string(int indent = 0) const;

 protected:
  Shape(TopoDS_Shape occurrence, std::shared_ptr<Entity> entity, std::shared_ptr<Registry> registry) noexcept;
  // A new root over `shape`, which must be of kind `expected`.
  Shape(const TopoDS_Shape& shape, Kind expected);

  // A child handle in this root, linked to this entity as its parent.
  Shape child(const TopoDS_Shape& shape, Kind kind) const;
  // A handle in this root for an entity that contains this one (an incident face of an edge): it becomes a
  // parent of this entity, not a child of it.
  Shape ancestor(const TopoDS_Shape& shape, Kind kind) const;

  Entity& entity() const noexcept { return *entity_; }
  Registry& registry() const noexcept { return *registry_; }

 private:
  friend class SemanticAccess;  // src/topo internals

  // This handle's own occurrence: it keeps the orientation and location it
  // was reached with (a face of a solid is REVERSED when the solid uses it
  // that way), which is not shared with other handles of the same entity.
  TopoDS_Shape shape_;
  std::shared_ptr<Entity> entity_;
  std::shared_ptr<Registry> registry_;
  // The write door of the semantic state: counts the write (see semantic_revision).
  SemanticState& writable_state();
};

// ---------------------------------------------------------------------------
// Typed handles.  They add behaviour only, never data.
// ---------------------------------------------------------------------------
class Vertex : public Shape {
 public:
  static constexpr Kind kKind = Kind::Vertex;
  explicit Vertex(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Vertex(const Shape& shape);

  Vec3 coordinates() const;
  std::vector<Edge> incident_edges() const;
};

class Edge : public Shape {
 public:
  static constexpr Kind kKind = Kind::Edge;
  explicit Edge(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Edge(const Shape& shape);

  double length() const;
  Vertex start_vertex() const;  // ValueError when the edge has no vertices
  Vertex end_vertex() const;
  std::vector<Vertex> vertices() const;
  std::vector<Face> incident_faces() const;
};

class Wire : public Shape {
 public:
  static constexpr Kind kKind = Kind::Wire;
  explicit Wire(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Wire(const Shape& shape);

  std::vector<Edge> edges() const;
  bool is_closed() const;
};

class Face : public Shape {
 public:
  static constexpr Kind kKind = Kind::Face;
  explicit Face(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Face(const Shape& shape);

  double area() const;
  Vec3 normal_at(double u = 0.5, double v = 0.5) const;
  Wire outer_wire() const;
  std::vector<Wire> wires() const;  // outer first
  std::vector<Wire> inner_wires() const;
  std::vector<Edge> edges() const;  // outer wire's edges, then the inner wires'
  std::vector<Face> adjacent_faces() const;
};

class Shell : public Shape {
 public:
  static constexpr Kind kKind = Kind::Shell;
  explicit Shell(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Shell(const Shape& shape);

  double area() const;
  bool is_closed() const;
  std::vector<Face> faces() const;
  std::vector<Wire> wires() const;  // free boundary wires
  std::vector<Edge> edges() const;  // unique across faces
};

class Solid : public Shape {
 public:
  static constexpr Kind kKind = Kind::Solid;
  explicit Solid(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Solid(const Shape& shape);

  double volume() const;
  std::vector<Face> faces() const;
  std::vector<Edge> edges() const;             // unique, in face order
  std::vector<Edge> edge_occurrences() const;  // once per use by a face

  // Tag faces by what they are: "box" | "cylinder" | "sphere" | anything else
  // (face_0, face_1, ...).  Applies face.<name> plus the wire/edge tags.
  void auto_tag_faces(std::string_view geometry_type = "unknown");
};

class Compound : public Shape {
 public:
  static constexpr Kind kKind = Kind::Compound;
  explicit Compound(const TopoDS_Shape& shape) : Shape(shape, kKind) {}
  explicit Compound(const Shape& shape);

  std::vector<Solid> solids() const;
  std::vector<Face> faces() const;
  std::vector<Edge> edges() const;  // unique
  double volume() const;
};

// Python-style indexing: negative counts from the end; IndexError when out of range.
template <class T>
const T& pick(const std::vector<T>& items, long index, std::string_view what);

}  // namespace scad

#include "scad/topo/shape_inl.hpp"
