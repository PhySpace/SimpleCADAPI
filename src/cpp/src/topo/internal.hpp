// Internals shared by the src/topo translation units.  Not installed.
#pragma once

#include <algorithm>
#include <functional>
#include <memory>
#include <optional>
#include <set>
#include <unordered_map>
#include <vector>

#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopoDS_Wire.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include "scad/core/packed_value.hpp"
#include "scad/core/symbol.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// Everything the SDK attaches to one topological entity.  Allocated on first
// write: most entities of a model are never tagged.
class SemanticState {
 public:
  SemanticState() = default;
  SemanticState(const SemanticState& other)
      : bindings(other.bindings),
        lineage(other.lineage),
        graph_node(other.graph_node),
        metadata_(other.metadata_ ? std::make_unique<Value>(*other.metadata_) : nullptr),
        runtime_(other.runtime_ ? std::make_unique<Value>(*other.runtime_) : nullptr),
        deferred_(other.deferred_) {}
  SemanticState& operator=(const SemanticState& other) {
    if (this != &other)
      *this = SemanticState(other);
    return *this;
  }
  SemanticState(SemanticState&&) noexcept = default;
  SemanticState& operator=(SemanticState&&) noexcept = default;

  std::vector<TagBinding> bindings;        // every stored binding, in insertion order: local and legacy snapshots
  std::vector<TagLineageWitness> lineage;  // evidence for lineage-scope tags
  // The graph node that produced this output (the SDK keeps the node object in the value's runtime).  Opaque
  // here: the reactive layer owns its type.  It keeps the node, and so its upstream, alive with the value.
  std::shared_ptr<const void> graph_node;
  // The tag names this entity holds are read off `bindings` (a handful of entries, compared by
  // interned-symbol pointer): no per-entity name caches to keep in step or to allocate.

  bool has_legacy() const noexcept {
    return std::any_of(bindings.begin(), bindings.end(),
                       [](const TagBinding& b) { return b.attachment == TagAttachment::EffectiveLegacy; });
  }

  // metadata / runtime dictionaries.  Both are allocated on first write.  A value written with
  // `defer` is held packed, in one byte string for all of the entity's deferred values, and is
  // expanded -- at the position it would have been inserted -- the first time the dictionary is
  // read or changed.
  Value& metadata() {
    settle(false);
    return dictionary(metadata_);
  }
  const Value& metadata() const {
    settle(false);
    return metadata_ ? *metadata_ : empty_object();
  }
  Value& runtime() {
    settle(true);
    return dictionary(runtime_);
  }
  const Value& runtime() const {
    settle(true);
    return runtime_ ? *runtime_ : empty_object();
  }
  // Whether the dictionary holds (or has deferred) `key`.
  bool has_key(bool runtime, std::string_view key) const {
    if (const Value* dict = (runtime ? runtime_ : metadata_).get(); dict != nullptr && dict->find(key) != nullptr)
      return true;
    bool found = false;
    each_deferred([&](bool is_runtime, std::uint32_t, Symbol k, std::string_view) {
      found = found || (is_runtime == runtime && k == key);
    });
    return found;
  }
  // Append `key` -> `value` (the key must be new) without building the Value tree.
  void defer(bool runtime, Symbol key, const Value& value) { defer_packed(runtime, key, PackedValue(value)); }
  void defer_packed(bool runtime, Symbol key, const PackedValue& packed) {
    std::size_t pos = dict_size(runtime);
    each_deferred([&](bool is_runtime, std::uint32_t, Symbol, std::string_view) { pos += is_runtime == runtime; });
    const std::string_view bytes = packed.bytes();
    deferred_.reserve(deferred_.size() + bytes.size() + 12);  // exact: no doubling slack on a record that stays
    deferred_.push_back(static_cast<char>(runtime ? 1 : 0));
    put_varint(pos);
    put_varint(key.index());
    put_varint(bytes.size());
    deferred_.append(bytes);
  }
  // One value, without expanding anything else (a deferred one is unpacked into `scratch`).
  const Value* peek(bool runtime, std::string_view key, Value& scratch) const {
    if (const Value* dict = (runtime ? runtime_ : metadata_).get())
      if (const Value* found = dict->find(key))
        return found;
    const Value* found = nullptr;
    each_deferred([&](bool is_runtime, std::uint32_t, Symbol k, std::string_view bytes) {
      if (is_runtime == runtime && k == key) {
        scratch = PackedValue::unpack_bytes(bytes);
        found = &scratch;
      }
    });
    return found;
  }
  const Value* peek_runtime(std::string_view key, Value& scratch) const { return peek(true, key, scratch); }
  // dictionary[key] = value without expanding what is deferred: a replaced entry keeps its place,
  // a new one goes to the end (packed, while anything is still deferred, so that it stays behind).
  void set_value(bool runtime, std::string key, Value value) {
    std::unique_ptr<Value>& slot = runtime ? runtime_ : metadata_;
    if (slot != nullptr && slot->find(key) != nullptr) {
      slot->set(std::move(key), std::move(value));
    } else if (!deferred_.empty() && !has_key(runtime, key)) {
      defer(runtime, Symbol(key), value);
    } else {
      (runtime ? this->runtime() : this->metadata()).set(std::move(key), std::move(value));
    }
  }
  bool empty_dictionaries() const noexcept {
    return dict_size(false) == 0 && dict_size(true) == 0 && deferred_.empty();
  }
  void clear_dictionaries() {
    metadata_.reset();
    runtime_.reset();
    deferred_.clear();
    deferred_.shrink_to_fit();
  }

 private:
  static const Value& empty_object() {
    static const Value empty = Value::object();
    return empty;
  }
  static Value& dictionary(std::unique_ptr<Value>& slot) {
    if (!slot)
      slot = std::make_unique<Value>(Value::object());
    return *slot;
  }
  std::size_t dict_size(bool runtime) const noexcept {
    const Value* dict = (runtime ? runtime_ : metadata_).get();
    return dict != nullptr ? dict->size() : 0;
  }
  void put_varint(std::uint64_t v) const {
    while (v >= 0x80) {
      deferred_.push_back(static_cast<char>(v | 0x80));
      v >>= 7;
    }
    deferred_.push_back(static_cast<char>(v));
  }
  static std::uint64_t get_varint(std::string_view in, std::size_t& at) {
    std::uint64_t v = 0;
    for (int shift = 0; at < in.size(); shift += 7) {
      const auto byte = static_cast<unsigned char>(in[at++]);
      v |= static_cast<std::uint64_t>(byte & 0x7F) << shift;
      if ((byte & 0x80) == 0)
        break;
    }
    return v;
  }
  // visit(is_runtime, position, key, packed value bytes) for every deferred entry, in order.
  template <class F>
  void each_deferred(F&& visit) const {
    const std::string_view in = deferred_;
    for (std::size_t at = 0; at < in.size();) {
      const bool is_runtime = in[at++] != 0;
      const auto pos = static_cast<std::uint32_t>(get_varint(in, at));
      const Symbol key = Symbol::from_index(static_cast<std::uint32_t>(get_varint(in, at)));
      const auto length = static_cast<std::size_t>(get_varint(in, at));
      visit(is_runtime, pos, key, in.substr(at, length));
      at += length;
    }
  }

  void settle(bool runtime) const {
    if (deferred_.empty())
      return;
    std::unique_ptr<Value>& slot = runtime ? runtime_ : metadata_;
    std::string rest;
    each_deferred([&](bool is_runtime, std::uint32_t pos, Symbol key, std::string_view bytes) {
      if (is_runtime != runtime) {
        // Keep the entry as it was: re-encode it verbatim.
        rest.push_back(static_cast<char>(is_runtime ? 1 : 0));
        append_varint(rest, pos);
        append_varint(rest, key.index());
        append_varint(rest, bytes.size());
        rest.append(bytes);
        return;
      }
      if (!slot)
        slot = std::make_unique<Value>(Value::object());
      auto& members = slot->as_object();
      members.insert(members.begin() + static_cast<std::ptrdiff_t>(std::min<std::size_t>(pos, members.size())),
                     Value::Member{key.str(), PackedValue::unpack_bytes(bytes)});
    });
    deferred_ = std::move(rest);
  }
  static void append_varint(std::string& out, std::uint64_t v) {
    while (v >= 0x80) {
      out.push_back(static_cast<char>(v | 0x80));
      v >>= 7;
    }
    out.push_back(static_cast<char>(v));
  }

  mutable std::unique_ptr<Value> metadata_;
  mutable std::unique_ptr<Value> runtime_;
  mutable std::string deferred_;
};

// The shared identity of a topological entity within one root.
struct Entity {
  Entity(Kind k, TopoDS_Shape s, Symbol id) : kind(k), topo_id(id), shape(std::move(s)) {}

  Kind kind;
  // Wire only: whether it is closed (-1: not asked yet).  Independent of the occurrence.
  std::int8_t closed = -1;
  // Face only: position of the outer wire among its wires in explorer order (-2: not asked yet,
  // -1: none).  Which wire is outer does not depend on the occurrence, and OuterWire is costly.
  std::int16_t outer_index = -2;
  Symbol topo_id;      // "face_3": the name table is shared by every root, so ids cost a pointer
  TopoDS_Shape shape;  // first occurrence seen; handles keep their own
  std::unique_ptr<SemanticState> sem;
  std::vector<std::weak_ptr<Entity>> parents;
  // A Shell's free-boundary wires are built by an analysis, not read from the shape: computed
  // once so the entities (tags, roles) a caller reaches through shell.wires() are stable.
  std::unique_ptr<std::vector<TopoDS_Wire>> free_wires;

  SemanticState& state() {
    if (!sem)
      sem = std::make_unique<SemanticState>();
    return *sem;
  }
  const SemanticState* state_if() const noexcept { return sem.get(); }
};

struct ShapeSame {
  bool operator()(const TopoDS_Shape& a, const TopoDS_Shape& b) const { return a.IsSame(b); }
};
struct ShapeHash {
  std::size_t operator()(const TopoDS_Shape& s) const { return std::hash<TopoDS_Shape>{}(s); }
};

// The distinct sub-shapes of one type under a root, in explorer order (what TopExp::MapShapes
// would index), as a flat vector and an open-addressing table of positions: a third of the memory
// of NCollection_IndexedMap (whose smallest bucket array is 101 slots, twice) and no node per entry.
class ShapeIndex {
 public:
  void build(const TopoDS_Shape& root, TopAbs_ShapeEnum type);
  // 1-based position of `shape` (IsSame), 0 when absent.
  int find(const TopoDS_Shape& shape) const;
  int extent() const noexcept { return static_cast<int>(keys_.size()); }

 private:
  void insert(const TopoDS_Shape& shape);
  std::vector<TopoDS_Shape> keys_;
  std::vector<std::uint32_t> slots_;  // position + 1; 0 is empty; size is a power of two
};

// Entity table of one root.  Numbering is by position in the root's own
// TopExp::MapShapes order, so topo ids do not depend on the order in which a
// caller happens to touch the topology.
class Registry {
 public:
  explicit Registry(TopoDS_Shape root) : root_(std::move(root)) {}

  const TopoDS_Shape& root() const noexcept { return root_; }
  std::shared_ptr<Entity> acquire(Kind kind, const TopoDS_Shape& shape);

  // Ancestor relations of the root, built on first use: for each `child`
  // sub-shape the `parent`-kind shapes that contain it.
  const TopTools_IndexedDataMapOfShapeListOfShape& ancestors(Kind child, Kind parent);

  // The entity of `shape` if it already exists (no entity is created).
  std::shared_ptr<Entity> peek(Kind kind, const TopoDS_Shape& shape);
  // Whether `shape` is a sub-shape of this root.
  bool contains(Kind kind, const TopoDS_Shape& shape);
  // Visit every entity created so far, in-root ones in topo-id order, then foreign ones.
  template <class F>
  void for_each_entity(F&& visit) const {
    for (const Table& table : tables_) {
      for (const auto& slot : table.by_index)
        if (slot)
          visit(*slot);
      for (const auto& item : table.foreign)
        visit(*item.second);
    }
  }

  // Set when any binding with downward propagation is stored on this root;
  // until then no entity can inherit a tag and inheritance lookups are skipped.
  bool has_downward_bindings = false;

 private:
  struct Table {
    ShapeIndex map;
    bool built = false;
    std::vector<std::shared_ptr<Entity>> by_index;
    std::unordered_map<TopoDS_Shape, std::shared_ptr<Entity>, ShapeHash, ShapeSame> foreign;
  };
  struct AncestorTable {
    Kind child, parent;
    TopTools_IndexedDataMapOfShapeListOfShape map;
  };

  TopoDS_Shape root_;
  Table tables_[7];
  std::vector<std::unique_ptr<AncestorTable>> ancestor_tables_;
};

// Friend of Shape: the way internal code reaches a handle's parts.
class SemanticAccess {
 public:
  static Entity& entity(const Shape& s) { return *s.entity_; }
  static const std::shared_ptr<Entity>& entity_ptr(const Shape& s) { return s.entity_; }
  static Registry& registry(const Shape& s) { return *s.registry_; }
  static const std::shared_ptr<Registry>& registry_ptr(const Shape& s) { return s.registry_; }
  static Shape make(TopoDS_Shape occurrence, std::shared_ptr<Entity> e, std::shared_ptr<Registry> r) {
    return Shape(std::move(occurrence), std::move(e), std::move(r));
  }
};

TopAbs_ShapeEnum to_topabs(Kind kind) noexcept;

}  // namespace scad
