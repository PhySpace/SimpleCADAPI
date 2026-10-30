// The QL property language: what a path such as "geom.center.z" means.
//
// A path is looked up in this order (_lookup_property):
//   1. "meta.<path>"           the shape's metadata only
//   2. "<path>"                the shape's metadata, as a dotted path
//   3. registered resolvers    longest registered prefix first
//   4. built-ins               topo.kind  topo.loop_role  geom.type  geom.family
//                              geom.bbox.{min,max}.{x,y,z}  geom.center.{x,y,z}
//                              geom.normal.{x,y,z}  geom.length  geom.area
//                              geom.volume  geom.closed
// "Missing" is std::nullopt, never a value: a predicate over a missing property
// is false.
//
// A path is compiled once (PropertyPath); looking it up parses nothing, and the
// kernel measurements behind the built-ins are made once per shape per query run
// (EvalContext).
#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/core/vec.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

// A resolver answers for the paths that start with the prefix it was registered
// under; std::nullopt means "not mine" and lookup continues.
using PropertyResolver = std::function<std::optional<Value>(const Shape&, std::string_view path)>;

// Registering the same prefix again replaces the resolver and keeps its place.
void register_property_resolver(std::string prefix, PropertyResolver resolver);
void unregister_property_resolver(std::string_view prefix);

struct ResolverEntry {
  std::string prefix;
  PropertyResolver resolve;
};

enum class Measure : unsigned char { Area, Length, Volume };

// What one query run needs to answer property lookups: the property resolvers as
// they were when the run started, and every measurement made so far.  A centre of
// mass or an area costs microseconds to milliseconds in the kernel and selectors ask
// for the same one again and again (a position range reads the centre twice per
// axis, order_by reads it once more), so each is made once per shape per context.
// A context belongs to one thread.
class EvalContext {
 public:
  EvalContext();

  [[nodiscard]] const std::vector<ResolverEntry>& resolvers() const noexcept { return *resolvers_; }

  // Edge / Face centre of mass, Vertex position; nullopt for other kinds (see center_of).
  [[nodiscard]] std::optional<Vec3> center(const Shape& shape) const;
  // The outward normal at the middle of a Face; nullopt for other kinds or an undefined normal.
  [[nodiscard]] std::optional<Vec3> normal(const Shape& shape) const;
  // Face/Shell area, Edge length, Solid/Compound volume; nullopt for other kinds or a kernel failure.
  [[nodiscard]] std::optional<double> measure(const Shape& shape, Measure what) const;
  // Throws like kernel::bounding_box (a shape without extent has none).
  [[nodiscard]] kernel::BoundingBox bbox(const Shape& shape) const;

 private:
  struct Memo;
  [[nodiscard]] Memo& memo() const;

  std::shared_ptr<const std::vector<ResolverEntry>> resolvers_;
  mutable std::shared_ptr<Memo> memo_;
};

// A dotted path into the metadata tree ("geo.size.x"), split once.
class MetadataPath {
 public:
  MetadataPath() = default;
  explicit MetadataPath(std::string_view path);
  // The value at the path inside `root`, or nullptr.  A stored null counts as absent.
  [[nodiscard]] const Value* find(const Value& root) const noexcept;
  [[nodiscard]] bool empty() const noexcept { return segments_.empty(); }

 private:
  std::vector<std::string> segments_;
};

class PropertyPath {
 public:
  explicit PropertyPath(std::string path);
  [[nodiscard]] const std::string& text() const noexcept { return path_; }
  [[nodiscard]] std::optional<Value> lookup(const Shape& shape, const EvalContext& ctx) const;

  enum class Builtin : unsigned char {
    None,
    TopoKind,
    TopoLoopRole,
    GeomType,
    GeomBBox,
    GeomFamily,
    GeomCenter,
    GeomNormal,
    GeomLength,
    GeomArea,
    GeomVolume,
    GeomClosed
  };

 private:
  std::string path_;
  bool metadata_only_ = false;  // "meta." prefix
  MetadataPath metadata_;       // the path (or, for "meta.", its tail)
  Builtin builtin_ = Builtin::None;
  int index_ = -1;  // bbox field 0..5 (xmin..zmax) or axis 0..2; -1 = invalid (never resolves)
};

// One-off conveniences (compile + lookup).
[[nodiscard]] std::optional<Value> lookup_property(const Shape& shape, std::string_view path);
// The metadata value at a dotted path; nullopt when absent or null.
[[nodiscard]] std::optional<Value> lookup_metadata(const Shape& shape, std::string_view path);

// The measured centre of an Edge or Face (centre of mass) and the position of a
// Vertex; nullopt for every other kind (_center_tuple).
[[nodiscard]] std::optional<Vec3> center_of(const Shape& shape);
// "LINE" / "CIRCLE" / ... for an Edge, "PLANE" / "CYLINDER" / ... for a Face.
[[nodiscard]] std::optional<std::string_view> geom_type(const Shape& shape);

}  // namespace scad::ql
