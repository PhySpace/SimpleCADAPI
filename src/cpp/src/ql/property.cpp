#include "scad/ql/property.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS.hxx>

#include <algorithm>
#include <mutex>
#include <unordered_map>
#include <utility>

#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ql/identity.hpp"

namespace scad::ql {

namespace {

// ---- the resolver registry -------------------------------------------------------------
class ResolverRegistry {
 public:
  void put(std::string prefix, PropertyResolver resolver) {
    Retired retired;  // declared before the lock: destroyed after it is released
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto found =
        std::find_if(entries_.begin(), entries_.end(), [&](const ResolverEntry& e) { return e.prefix == prefix; });
    if (found != entries_.end()) {
      retired.resolver = std::exchange(found->resolve, std::move(resolver));
    } else {
      entries_.push_back({std::move(prefix), std::move(resolver)});
    }
    retired.snapshot = publish();
  }

  void remove(std::string_view prefix) {
    Retired retired;
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto found =
        std::find_if(entries_.begin(), entries_.end(), [&](const ResolverEntry& e) { return e.prefix == prefix; });
    if (found == entries_.end())
      return;
    retired.resolver = std::move(found->resolve);
    entries_.erase(found);
    retired.snapshot = publish();
  }

  std::shared_ptr<const std::vector<ResolverEntry>> snapshot() const {
    const std::lock_guard<std::mutex> lock(mutex_);
    return snapshot_;
  }

 private:
  // What a change drops.  A resolver written in Python runs arbitrary code when it is destroyed,
  // so that must not happen while the registry is locked.
  struct Retired {
    PropertyResolver resolver;
    std::shared_ptr<const std::vector<ResolverEntry>> snapshot;
  };

  // Rebuilds the published snapshot (longest prefix first, registration order among equals)
  // and hands back the one it replaces.
  std::shared_ptr<const std::vector<ResolverEntry>> publish() {
    auto sorted = entries_;
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const ResolverEntry& a, const ResolverEntry& b) { return a.prefix.size() > b.prefix.size(); });
    auto replaced = std::move(snapshot_);
    snapshot_ = std::make_shared<const std::vector<ResolverEntry>>(std::move(sorted));
    return replaced;
  }

  mutable std::mutex mutex_;
  std::vector<ResolverEntry> entries_;
  std::shared_ptr<const std::vector<ResolverEntry>> snapshot_ = std::make_shared<const std::vector<ResolverEntry>>();
};

ResolverRegistry& registry() {
  static ResolverRegistry instance;
  return instance;
}

// ---- built-ins -----------------------------------------------------------------------------
constexpr std::string_view kBBoxFields[6] = {"min.x", "min.y", "min.z", "max.x", "max.y", "max.z"};

int axis_index(std::string_view axis) noexcept {
  if (axis == "x")
    return 0;
  if (axis == "y")
    return 1;
  if (axis == "z")
    return 2;
  return -1;
}

double coordinate(const Vec3& v, int index) {
  return index == 0 ? v.x : (index == 1 ? v.y : v.z);
}

std::string_view curve_type_name(GeomAbs_CurveType type) {
  switch (type) {
    case GeomAbs_Line:
      return "LINE";
    case GeomAbs_Circle:
      return "CIRCLE";
    case GeomAbs_Ellipse:
      return "ELLIPSE";
    case GeomAbs_Hyperbola:
      return "HYPERBOLA";
    case GeomAbs_Parabola:
      return "PARABOLA";
    case GeomAbs_BezierCurve:
      return "BEZIER";
    case GeomAbs_BSplineCurve:
      return "BSPLINE";
    case GeomAbs_OffsetCurve:
      return "OFFSETCURVE";
    case GeomAbs_OtherCurve:
      return "OTHERCURVE";
  }
  return "OTHERCURVE";
}

std::string_view surface_type_name(GeomAbs_SurfaceType type) {
  switch (type) {
    case GeomAbs_Plane:
      return "PLANE";
    case GeomAbs_Cylinder:
      return "CYLINDER";
    case GeomAbs_Cone:
      return "CONE";
    case GeomAbs_Sphere:
      return "SPHERE";
    case GeomAbs_Torus:
      return "TORUS";
    case GeomAbs_BezierSurface:
      return "BEZIER";
    case GeomAbs_BSplineSurface:
      return "BSPLINE";
    case GeomAbs_SurfaceOfRevolution:
      return "SURFACEOFREVOLUTION";
    case GeomAbs_SurfaceOfExtrusion:
      return "SURFACEOFEXTRUSION";
    case GeomAbs_OffsetSurface:
      return "OFFSETSURFACE";
    case GeomAbs_OtherSurface:
      return "OTHERSURFACE";
  }
  return "OTHERSURFACE";
}

std::optional<Value> as_value(const std::optional<double>& number) {
  if (!number)
    return std::nullopt;
  return Value(*number);
}

std::optional<Value> loop_role(const Shape& shape) {
  try {
    if (shape.has_tag("wire.outer"))
      return Value("outer");
    if (shape.has_tag("wire.inner"))
      return Value("inner");
  } catch (const SemanticCapabilityError&) {
    throw;
  } catch (const std::exception&) {
    // Kept broad: has_tag's other failures are not enumerable here.  A shape whose tags cannot be read has
    // no loop role; the property is then simply absent.
    return std::nullopt;
  }
  return std::nullopt;
}

std::optional<Value> family(Kind kind) {
  switch (kind) {
    case Kind::Edge:
      return Value("curve");
    case Kind::Face:
      return Value("surface");
    case Kind::Solid:
      return Value("body");
    case Kind::Compound:
      return Value("compound");
    case Kind::Wire:
      return Value("wire");
    case Kind::Vertex:
      return Value("point");
    case Kind::Shell:
      break;
  }
  return std::nullopt;
}

}  // namespace

void register_property_resolver(std::string prefix, PropertyResolver resolver) {
  if (prefix.empty())
    throw ValueError("prefix must be a non-empty string");
  registry().put(std::move(prefix), std::move(resolver));
}

void unregister_property_resolver(std::string_view prefix) {
  registry().remove(prefix);
}

template <class T>
struct Memoised {
  bool known = false;
  std::optional<T> value;
};

struct EvalContext::Memo {
  struct Entry {
    Memoised<Vec3> center;
    Memoised<Vec3> normal;
    Memoised<double> measures[3];
    Memoised<kernel::BoundingBox> bbox;
  };
  std::unordered_map<Shape, Entry, IdentityHash, IdentityEqual> entries;
};

EvalContext::EvalContext() : resolvers_(registry().snapshot()) {}

EvalContext::Memo& EvalContext::memo() const {
  if (!memo_)
    memo_ = std::make_shared<Memo>();
  return *memo_;
}

std::optional<Vec3> EvalContext::center(const Shape& shape) const {
  auto& slot = memo().entries[shape].center;
  if (!slot.known) {
    slot.value = center_of(shape);
    slot.known = true;
  }
  return slot.value;
}

std::optional<Vec3> EvalContext::normal(const Shape& shape) const {
  auto& slot = memo().entries[shape].normal;
  if (!slot.known) {
    slot.known = true;
    if (shape.kind() == Kind::Face) {
      try {
        slot.value = kernel::face_normal_at(TopoDS::Face(shape.wrapped()));
      } catch (const Exception&) {
        // face_normal_at runs under occt_guard (KernelError/ValueError): a normal the kernel cannot
        // compute is a missing property, not an error.
        slot.value = std::nullopt;
      }
    }
  }
  return slot.value;
}

std::optional<double> EvalContext::measure(const Shape& shape, Measure what) const {
  auto& slot = memo().entries[shape].measures[static_cast<std::size_t>(what)];
  if (slot.known)
    return slot.value;
  slot.known = true;
  const Kind kind = shape.kind();
  try {
    switch (what) {
      case Measure::Area:
        if (kind == Kind::Face || kind == Kind::Shell)
          slot.value = kernel::surface_area(shape.wrapped());
        break;
      case Measure::Length:
        if (kind == Kind::Edge)
          slot.value = kernel::linear_length(shape.wrapped());
        break;
      case Measure::Volume:
        if (kind == Kind::Solid)
          slot.value = kernel::volume(shape.wrapped());
        if (kind == Kind::Compound)
          slot.value = Compound(shape).volume();
        break;
    }
  } catch (const Exception&) {
    // The kernel measures run under occt_guard (KernelError/ValueError): a measurement the kernel cannot
    // make is missing, not an error.
    slot.value = std::nullopt;
  }
  return slot.value;
}

kernel::BoundingBox EvalContext::bbox(const Shape& shape) const {
  auto& slot = memo().entries[shape].bbox;
  if (!slot.known) {
    slot.value = kernel::bounding_box(shape.wrapped());
    slot.known = true;
  }
  return *slot.value;
}

// ---- MetadataPath ---------------------------------------------------------------------------------
MetadataPath::MetadataPath(std::string_view path) {
  if (path.empty())
    return;
  std::size_t start = 0;
  for (;;) {
    const std::size_t dot = path.find('.', start);
    if (dot == std::string_view::npos) {
      segments_.emplace_back(path.substr(start));
      return;
    }
    segments_.emplace_back(path.substr(start, dot - start));
    start = dot + 1;
  }
}

const Value* MetadataPath::find(const Value& root) const noexcept {
  if (segments_.empty())
    return nullptr;
  const Value* current = &root;
  for (const std::string& segment : segments_) {
    if (!current->is_object())
      return nullptr;
    current = current->find(segment);
    if (current == nullptr)
      return nullptr;
  }
  return current->is_null() ? nullptr : current;
}

// ---- PropertyPath -----------------------------------------------------------------------------------
PropertyPath::PropertyPath(std::string path) : path_(std::move(path)) {
  if (path_.empty())
    return;
  if (path_.starts_with("meta.")) {
    metadata_only_ = true;
    metadata_ = MetadataPath(std::string_view(path_).substr(5));
    return;
  }
  metadata_ = MetadataPath(path_);

  const std::string_view text = path_;
  const auto tail_axis = [&] { return axis_index(text.substr(text.rfind('.') + 1)); };
  if (text == "topo.kind")
    builtin_ = Builtin::TopoKind;
  else if (text == "topo.loop_role")
    builtin_ = Builtin::TopoLoopRole;
  else if (text == "geom.type")
    builtin_ = Builtin::GeomType;
  else if (text == "geom.family")
    builtin_ = Builtin::GeomFamily;
  else if (text == "geom.length")
    builtin_ = Builtin::GeomLength;
  else if (text == "geom.area")
    builtin_ = Builtin::GeomArea;
  else if (text == "geom.volume")
    builtin_ = Builtin::GeomVolume;
  else if (text == "geom.closed")
    builtin_ = Builtin::GeomClosed;
  else if (text.starts_with("geom.bbox.")) {
    builtin_ = Builtin::GeomBBox;
    const std::string_view field = text.substr(10);
    for (int i = 0; i < 6; ++i)
      if (kBBoxFields[i] == field)
        index_ = i;
  } else if (text.starts_with("geom.center.")) {
    builtin_ = Builtin::GeomCenter;
    index_ = tail_axis();
  } else if (text.starts_with("geom.normal.")) {
    builtin_ = Builtin::GeomNormal;
    index_ = tail_axis();
  }
}

std::optional<Value> PropertyPath::lookup(const Shape& shape, const EvalContext& ctx) const {
  if (path_.empty())
    return std::nullopt;
  const Value& metadata = shape.metadata();
  if (const Value* found = metadata_.find(metadata))
    return *found;
  if (metadata_only_)
    return std::nullopt;

  for (const ResolverEntry& entry : ctx.resolvers()) {
    if (!path_.starts_with(entry.prefix))
      continue;
    if (std::optional<Value> answer = entry.resolve(shape, path_))
      return answer;
  }

  const Kind kind = shape.kind();
  switch (builtin_) {
    case Builtin::None:
      return std::nullopt;
    case Builtin::TopoKind:
      if (kind == Kind::Shell)
        return std::nullopt;
      return Value(kind_name(kind));
    case Builtin::TopoLoopRole:
      return loop_role(shape);
    case Builtin::GeomType: {
      const auto type = geom_type(shape);
      if (!type)
        return std::nullopt;
      return Value(*type);
    }
    case Builtin::GeomFamily:
      return family(kind);
    case Builtin::GeomBBox: {
      if (index_ < 0)
        return std::nullopt;
      const kernel::BoundingBox box = ctx.bbox(shape);
      // min.x min.y min.z max.x max.y max.z
      const double fields[6] = {box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax};
      return Value(fields[index_]);
    }
    case Builtin::GeomCenter: {
      if (index_ < 0)
        return std::nullopt;
      const auto center = ctx.center(shape);
      if (!center)
        return std::nullopt;
      return Value(coordinate(*center, index_));
    }
    case Builtin::GeomNormal: {
      if (index_ < 0)
        return std::nullopt;
      const auto normal = ctx.normal(shape);
      if (!normal)
        return std::nullopt;
      return Value(coordinate(*normal, index_));
    }
    case Builtin::GeomLength:
      return as_value(ctx.measure(shape, Measure::Length));
    case Builtin::GeomArea:
      return as_value(ctx.measure(shape, Measure::Area));
    case Builtin::GeomVolume:
      return as_value(ctx.measure(shape, Measure::Volume));
    case Builtin::GeomClosed:
      try {
        if (kind == Kind::Wire)
          return Value(kernel::is_wire_closed(TopoDS::Wire(shape.wrapped())));
        if (kind == Kind::Shell)
          return Value(kernel::shell_is_closed(shape.wrapped()));
      } catch (const std::exception&) {
        // Kept broad: kernel::is_wire_closed/shell_is_closed are not under occt_guard, so this is not
        // known to be narrowable.  A closedness the kernel cannot tell is a missing property.
        return std::nullopt;
      }
      return std::nullopt;
  }
  return std::nullopt;
}

std::optional<Value> lookup_property(const Shape& shape, std::string_view path) {
  const EvalContext ctx;
  return PropertyPath(std::string(path)).lookup(shape, ctx);
}

std::optional<Value> lookup_metadata(const Shape& shape, std::string_view path) {
  const Value* found = MetadataPath(path).find(shape.metadata());
  if (found == nullptr)
    return std::nullopt;
  return *found;
}

std::optional<Vec3> center_of(const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Vertex:
      try {
        return Vertex(shape).coordinates();
      } catch (const std::exception&) {
        return std::nullopt;
      }
    case Kind::Face:
      try {
        return shape.center();
      } catch (const std::exception&) {
        return std::nullopt;
      }
    case Kind::Edge: {
      std::optional<Vec3> mass_centre;
      try {
        mass_centre = shape.center();
      } catch (const Exception&) {
        // center_of_mass runs under occt_guard (KernelError/ValueError): fall back to the end points below.
        mass_centre = std::nullopt;
      }
      if (mass_centre)
        return mass_centre;
      try {  // the centre of mass failed: fall back to the midpoint of the end points
        const Edge edge(shape);
        return (edge.start_vertex().coordinates() + edge.end_vertex().coordinates()) / 2.0;
      } catch (const std::exception&) {
        return std::nullopt;
      }
    }
    default:
      return std::nullopt;
  }
}

std::optional<std::string_view> geom_type(const Shape& shape) {
  try {
    return occt_guard([&]() -> std::optional<std::string_view> {
      if (shape.kind() == Kind::Edge)
        return curve_type_name(BRepAdaptor_Curve(TopoDS::Edge(shape.wrapped())).GetType());
      if (shape.kind() == Kind::Face)
        return surface_type_name(BRepAdaptor_Surface(TopoDS::Face(shape.wrapped())).GetType());
      return std::nullopt;
    });
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

}  // namespace scad::ql
