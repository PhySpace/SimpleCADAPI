#include "scad/io/serialize.hpp"

#include <array>
#include <optional>

#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include "bytes.hpp"
#include "scad/core/error.hpp"
#include "scad/io/brep.hpp"
#include "scad/io/hash.hpp"
#include "tag_codec.hpp"

namespace scad::io {

namespace {

constexpr std::string_view kMagic = "SCADSHAP";
constexpr std::size_t kHeaderSize = 40;
constexpr std::string_view kStateFormat = "scad-shape-state";
constexpr std::int64_t kStateVersion = 1;
constexpr std::string_view kDerivedRuntimePrefix = "mesh.";  // derived data: recomputed, never stored

constexpr std::array<Kind, 7> kAllKinds{Kind::Vertex, Kind::Edge,  Kind::Wire,    Kind::Face,
                                        Kind::Shell,  Kind::Solid, Kind::Compound};

TopAbs_ShapeEnum topabs_of(Kind kind) {
  switch (kind) {
    case Kind::Vertex:
      return TopAbs_VERTEX;
    case Kind::Edge:
      return TopAbs_EDGE;
    case Kind::Wire:
      return TopAbs_WIRE;
    case Kind::Face:
      return TopAbs_FACE;
    case Kind::Shell:
      return TopAbs_SHELL;
    case Kind::Solid:
      return TopAbs_SOLID;
    case Kind::Compound:
      return TopAbs_COMPOUND;
  }
  return TopAbs_SHAPE;
}

Kind kind_from_name(const std::string& name) {
  for (const Kind kind : kAllKinds)
    if (kind_name(kind) == name)
      return kind;
  throw ValueError("the shape state names an unknown entity kind '" + name + "'");
}

bool is_derived(const std::string& runtime_key) {
  return std::string_view(runtime_key).substr(0, kDerivedRuntimePrefix.size()) == kDerivedRuntimePrefix;
}

Value stored_runtime(const Value& runtime) {
  Value out = Value::object();
  for (const auto& [key, item] : runtime.as_object())
    if (!is_derived(key))
      out.set(key, item);
  return out;
}

// One record per entity under `root` that carries any semantic state.
Value capture_entities(const Shape& root) {
  Value entities = Value::array();
  for (const Kind kind : kAllKinds) {
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(root.wrapped(), topabs_of(kind), map);
    for (int index = 1; index <= map.Extent(); ++index) {
      const Shape entity = root.sub(map.FindKey(index));
      const auto& bindings = entity.local_bindings();
      const auto& lineage = entity.lineage_witnesses();
      Value runtime = stored_runtime(entity.runtime());
      if (bindings.empty() && lineage.empty() && entity.metadata().size() == 0 && runtime.size() == 0)
        continue;

      Value record = Value::object();
      record.set("kind", std::string(kind_name(kind)));
      record.set("index", index);
      record.set("topo_id", entity.topo_id());
      Value binding_values = Value::array();
      for (const TagBinding& b : bindings)
        binding_values.push_back(b.to_value());
      record.set("bindings", std::move(binding_values));
      Value lineage_values = Value::array();
      for (const TagLineageWitness& w : lineage)
        lineage_values.push_back(w.to_value());
      record.set("lineage", std::move(lineage_values));
      record.set("metadata", entity.metadata());
      record.set("runtime", std::move(runtime));
      entities.push_back(std::move(record));
    }
  }
  return entities;
}

const Value& required(const Value& object, std::string_view key) {
  if (!object.is_object())
    throw ValueError("the shape state is malformed: expected an object");
  const Value* found = object.find(key);
  if (found == nullptr)
    throw ValueError("the shape state is malformed: missing '" + std::string(key) + "'");
  return *found;
}

void restore_entities(const Shape& root, const Value& entities) {
  std::array<std::optional<TopTools_IndexedMapOfShape>, 7> maps;
  for (const Value& record : entities.as_array()) {
    const Kind kind = kind_from_name(required(record, "kind").as_string());
    auto& map = maps[static_cast<std::size_t>(kind)];
    if (!map) {
      map.emplace();
      TopExp::MapShapes(root.wrapped(), topabs_of(kind), *map);
    }
    const std::int64_t index = required(record, "index").as_int();
    if (index < 1 || index > map->Extent())
      throw ValueError(std::string("the saved ") + std::string(kind_name(kind)) + " #" + std::to_string(index) +
                       " is outside the restored shape");
    Shape entity = root.sub(map->FindKey(static_cast<int>(index)));
    for (const Value& binding : required(record, "bindings").as_array())
      entity.add_binding(detail::binding_from_value(binding));
    for (const Value& witness : required(record, "lineage").as_array())
      entity.add_lineage_witness(detail::witness_from_value(witness));
    for (const auto& [key, item] : required(record, "metadata").as_object())
      entity.set_metadata(key, item);
    for (const auto& [key, item] : required(record, "runtime").as_object())
      entity.set_runtime(key, item);
  }
}

const ErrorSpec& serialize_spec() {
  static const ErrorSpec spec{"serialize_shape",
                              "Failed to serialize the shape.",
                              {"The shape is null or its geometry cannot be written by OpenCASCADE.",
                               "A metadata value cannot be represented (only JSON-like values are stored)."},
                              {"Pass a non-null Vertex, Edge, Wire, Face, Shell, Solid or Compound.",
                               "Keep metadata to None, bool, int, float, str, list and dict values."}};
  return spec;
}

const ErrorSpec& deserialize_spec() {
  static const ErrorSpec spec{
      "deserialize_shape",
      "Failed to restore a serialized shape.",
      {"The bytes are truncated or corrupted.", "The bytes were not produced by serialize() (wrong magic or checksum).",
       "The bytes use a newer incompatible format version."},
      {"Pass exactly the bytes serialize() returned.", "Re-serialize the shape with this library version."}};
  return spec;
}

}  // namespace

Bytes serialize(const Shape& shape) {
  return guarded(serialize_spec(), [&]() -> Bytes {
    Value state = Value::object();
    state.set("format", std::string(kStateFormat));
    state.set("version", kStateVersion);
    state.set("root_kind", std::string(kind_name(shape.kind())));
    state.set("entities", capture_entities(shape));

    detail::ByteWriter state_bytes;
    detail::encode_value(state_bytes, state);
    const std::string state_section = state_bytes.take();
    const Bytes brep_section = to_brep_bytes(shape.wrapped());

    std::string body;
    body.reserve(state_section.size() + brep_section.size());
    body += state_section;
    body += brep_section;

    detail::ByteWriter out;
    out.raw(kMagic);
    out.u16(kSerializeMajorVersion);
    out.u16(kSerializeMinorVersion);
    out.u32(0);
    out.u64(state_section.size());
    out.u64(brep_section.size());
    out.u32(crc32(body));
    out.u32(0);
    out.raw(body);
    return out.take();
  });
}

Shape deserialize(std::string_view bytes) {
  return guarded(deserialize_spec(), [&]() -> Shape {
    detail::ByteReader header(bytes, "serialized shape");
    if (bytes.size() < kHeaderSize || header.bytes(kMagic.size()) != kMagic)
      throw ValueError("not a serialized shape (bad magic)");
    const std::uint16_t major = header.u16();
    const std::uint16_t minor = header.u16();
    if (major != kSerializeMajorVersion)
      throw ValueError("unsupported serialized shape version " + std::to_string(major) + "." + std::to_string(minor));
    if (header.u32() != 0)
      throw ValueError("the serialized shape uses unsupported flags");
    const std::uint64_t state_size = header.u64();
    const std::uint64_t brep_size = header.u64();
    const std::uint32_t checksum = header.u32();
    (void)header.u32();  // reserved
    if (state_size > header.remaining() || brep_size != header.remaining() - state_size)
      throw ValueError("the serialized shape's length does not match its header");
    const std::string_view body = bytes.substr(kHeaderSize);
    if (crc32(body) != checksum)
      throw ValueError("the serialized shape is corrupted (checksum mismatch)");

    detail::ByteReader state_reader(body.substr(0, static_cast<std::size_t>(state_size)), "shape state");
    const Value state = detail::decode_value(state_reader);
    if (state_reader.remaining() != 0)
      throw ValueError("the shape state has trailing data");
    if (required(state, "format").as_string() != kStateFormat)
      throw ValueError("the shape state has a wrong format tag");
    if (required(state, "version").as_int() != kStateVersion)
      throw ValueError("unsupported shape state version");

    const TopoDS_Shape geometry = from_brep_bytes(body.substr(static_cast<std::size_t>(state_size)));
    Shape root = Shape::from_occt(geometry);
    if (kind_name(root.kind()) != required(state, "root_kind").as_string())
      throw ValueError("the serialized geometry is not of the declared kind");
    restore_entities(root, required(state, "entities"));
    return root;
  });
}

}  // namespace scad::io
