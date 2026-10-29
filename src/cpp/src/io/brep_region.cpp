#include "scad/io/brep_region.hpp"

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <set>

#include <BRepAdaptor_Surface.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Standard_Version.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>

#include "bytes.hpp"
#include "numfmt.hpp"
#include "scad/core/error.hpp"
#include "scad/io/brep.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"

namespace scad::io {

namespace {

constexpr std::string_view kOperation = "brep_region";
constexpr std::string_view kBinToolsV4Preamble = "\nOpen CASCADE Topology V4, (c) Open Cascade\n";
constexpr double kRelativeTolerance = 1e-9;

[[noreturn]] void fail(const std::string& message) {
  throw MessageError(std::string(kOperation), message);
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
std::int64_t shape_count(const TopoDS_Shape& shape, TopAbs_ShapeEnum kind) {
  TopTools_IndexedMapOfShape map;
  TopExp::MapShapes(shape, kind, map);
  return map.Extent();
}

double round_to_12_places(double value) {
  char buffer[400];
  const auto written = std::to_chars(buffer, buffer + sizeof buffer, value, std::chars_format::fixed, 12);
  double rounded = value;
  if (written.ec == std::errc() && detail::parse_double(std::string_view(buffer, written.ptr), rounded))
    return rounded;
  return value;
}

bool close_enough(double a, double b) {
  return std::fabs(a - b) <= kRelativeTolerance * std::max({1.0, std::fabs(a), std::fabs(b)});
}

bool is_count(const Value& v) {
  return v.is_int() && v.as_int() >= 0;
}
bool is_finite_number(const Value& v) {
  return v.is_number() && std::isfinite(v.as_double());
}
bool is_sha256(const Value& v) {
  if (!v.is_string())
    return false;
  const std::string& s = v.as_string();
  if (s.size() != 7 + 64 || s.compare(0, 7, "sha256:") != 0)
    return false;
  return std::all_of(s.begin() + 7, s.end(), [](char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); });
}
bool is_face_id(const Value& v) {
  if (!v.is_string())
    return false;
  const std::string& s = v.as_string();
  if (s.size() < 6 || s.compare(0, 5, "face:") != 0)
    return false;
  const std::string_view digits = std::string_view(s).substr(5);
  if (!std::all_of(digits.begin(), digits.end(), [](char c) { return c >= '0' && c <= '9'; }))
    return false;
  return digits == "0" || digits.front() != '0';
}

const char* orientation_name(TopAbs_Orientation orientation) {
  switch (orientation) {
    case TopAbs_FORWARD:
      return "TopAbs_FORWARD";
    case TopAbs_REVERSED:
      return "TopAbs_REVERSED";
    case TopAbs_INTERNAL:
      return "TopAbs_INTERNAL";
    case TopAbs_EXTERNAL:
      return "TopAbs_EXTERNAL";
  }
  return "TopAbs_FORWARD";
}

const char* surface_type_name(GeomAbs_SurfaceType type) {
  switch (type) {
    case GeomAbs_Plane:
      return "GeomAbs_Plane";
    case GeomAbs_Cylinder:
      return "GeomAbs_Cylinder";
    case GeomAbs_Cone:
      return "GeomAbs_Cone";
    case GeomAbs_Sphere:
      return "GeomAbs_Sphere";
    case GeomAbs_Torus:
      return "GeomAbs_Torus";
    case GeomAbs_BezierSurface:
      return "GeomAbs_BezierSurface";
    case GeomAbs_BSplineSurface:
      return "GeomAbs_BSplineSurface";
    case GeomAbs_SurfaceOfRevolution:
      return "GeomAbs_SurfaceOfRevolution";
    case GeomAbs_SurfaceOfExtrusion:
      return "GeomAbs_SurfaceOfExtrusion";
    case GeomAbs_OffsetSurface:
      return "GeomAbs_OffsetSurface";
    case GeomAbs_OtherSurface:
      return "GeomAbs_OtherSurface";
  }
  return "GeomAbs_OtherSurface";
}

// "7.9.3.1" -> {7, 9}; nullopt when it does not start with two integers.
std::optional<std::pair<int, int>> major_minor(std::string_view version) {
  int parts[2] = {0, 0};
  std::size_t at = 0;
  for (int& part : parts) {
    const std::size_t end = version.find('.', at);
    const std::string_view token = version.substr(at, end == std::string_view::npos ? end : end - at);
    if (token.empty() || !std::all_of(token.begin(), token.end(), [](char c) { return c >= '0' && c <= '9'; }) ||
        token.size() > 6)
      return std::nullopt;
    part = std::stoi(std::string(token));
    if (end == std::string_view::npos) {
      if (&part == &parts[0])
        return std::nullopt;
      break;
    }
    at = end + 1;
  }
  return std::pair{parts[0], parts[1]};
}

}  // namespace

std::string_view to_string(RegionRootKind kind) noexcept {
  return kind == RegionRootKind::Solid ? "solid" : "shell";
}

std::string default_ocp_version() {
  return OCC_VERSION_COMPLETE;
}

std::string region_profile(std::string_view ocp_version) {
  return "scadbrep-1-ocp-" + std::string(ocp_version) + "-bintools-v4-no-mesh";
}

// ---------------------------------------------------------------------------
// Descriptors
// ---------------------------------------------------------------------------
Value ShapeDescriptor::to_value() const {
  Value v = Value::object();
  v.set("root_shape_type", std::string(to_string(root_kind)));
  v.set("valid", valid);
  v.set("solid_count", solid_count);
  v.set("shell_count", shell_count);
  v.set("face_count", face_count);
  v.set("edge_count", edge_count);
  v.set("vertex_count", vertex_count);
  if (volume)
    v.set("volume", *volume);
  if (closed)
    v.set("closed", *closed);
  return v;
}

bool has_triangulation(const TopoDS_Shape& shape) {
  for (TopExp_Explorer faces(shape, TopAbs_FACE); faces.More(); faces.Next()) {
    TopLoc_Location location;
    if (!BRep_Tool::Triangulation(TopoDS::Face(faces.Current()), location).IsNull())
      return true;
  }
  return false;
}

namespace {

ShapeDescriptor common_descriptor(const TopoDS_Shape& shape, RegionRootKind kind) {
  ShapeDescriptor d;
  d.root_kind = kind;
  d.valid = BRepCheck_Analyzer(shape).IsValid() == Standard_True;
  d.solid_count = shape_count(shape, TopAbs_SOLID);
  d.shell_count = shape_count(shape, TopAbs_SHELL);
  d.face_count = shape_count(shape, TopAbs_FACE);
  d.edge_count = shape_count(shape, TopAbs_EDGE);
  d.vertex_count = shape_count(shape, TopAbs_VERTEX);
  return d;
}

template <class T>
std::vector<T> collect(const TopoDS_Shape& shape, TopAbs_ShapeEnum kind, T (*cast)(const TopoDS_Shape&)) {
  std::vector<T> items;
  if (shape.ShapeType() == kind) {
    items.push_back(cast(shape));
  } else {
    for (TopExp_Explorer explorer(shape, kind); explorer.More(); explorer.Next())
      items.push_back(cast(explorer.Current()));
  }
  return items;
}

}  // namespace

ShapeDescriptor shell_descriptor(const TopoDS_Shell& shell) {
  return occt_guard([&] {
    ShapeDescriptor d = common_descriptor(shell, RegionRootKind::Shell);
    d.closed = BRep_Tool::IsClosed(shell) == Standard_True;
    return d;
  });
}

ShapeDescriptor solid_descriptor(const TopoDS_Solid& solid) {
  return occt_guard([&] {
    GProp_GProps properties;
    BRepGProp::VolumeProperties(solid, properties);
    const double volume = properties.Mass();
    if (!std::isfinite(volume) || volume <= 0.0)
      throw ValueError("BREP region must have positive finite solid volume");
    ShapeDescriptor d = common_descriptor(solid, RegionRootKind::Solid);
    d.volume = volume;
    return d;
  });
}

TopoDS_Shell require_single_valid_shell(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    const auto shells =
        collect<TopoDS_Shell>(shape, TopAbs_SHELL, [](const TopoDS_Shape& s) { return TopoDS::Shell(s); });
    if (shells.size() != 1)
      throw ValueError("BREP region must contain exactly one shell, got " + std::to_string(shells.size()));
    const TopoDS_Shell& shell = shells.front();
    if (shape_count(shape, TopAbs_FACE) != shape_count(shell, TopAbs_FACE))
      throw ValueError("BREP region contains faces outside its single shell");
    if (!shell_descriptor(shell).valid)
      throw ValueError("BREP region shell is invalid");
    return shell;
  });
}

TopoDS_Solid require_single_valid_solid(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    const auto solids =
        collect<TopoDS_Solid>(shape, TopAbs_SOLID, [](const TopoDS_Shape& s) { return TopoDS::Solid(s); });
    if (solids.size() != 1)
      throw ValueError("BREP region must contain exactly one solid, got " + std::to_string(solids.size()));
    const TopoDS_Solid& solid = solids.front();
    for (const TopAbs_ShapeEnum kind : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX})
      if (shape_count(shape, kind) != shape_count(solid, kind))
        throw ValueError("BREP region contains topology outside its single solid");
    if (!solid_descriptor(solid).valid)
      throw ValueError("BREP region solid is invalid");
    return solid;
  });
}

ShapeDescriptor shape_descriptor(const TopoDS_Shape& shape, RegionRootKind kind) {
  return kind == RegionRootKind::Solid ? solid_descriptor(require_single_valid_solid(shape))
                                       : shell_descriptor(require_single_valid_shell(shape));
}

Value face_fingerprints(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    Value records = Value::array();
    for (int index = 1; index <= faces.Extent(); ++index) {
      const TopoDS_Face face = TopoDS::Face(faces.FindKey(index));
      GProp_GProps properties;
      BRepGProp::SurfaceProperties(face, properties);
      const gp_Pnt center = properties.CentreOfMass();
      Value record = Value::object();
      record.set("surface_type", surface_type_name(BRepAdaptor_Surface(face, Standard_True).GetType()));
      record.set("orientation", orientation_name(face.Orientation()));
      record.set("area", round_to_12_places(std::fabs(properties.Mass())));
      Value centroid = Value::array();
      for (const double c : {center.X(), center.Y(), center.Z()})
        centroid.push_back(round_to_12_places(c));
      record.set("centroid", std::move(centroid));
      record.set("edge_count", shape_count(face, TopAbs_EDGE));
      records.push_back(std::move(record));
    }
    return records;
  });
}

Bytes encode_shape(const TopoDS_Shape& shape, RegionRootKind kind) {
  if (kind == RegionRootKind::Solid)
    (void)require_single_valid_solid(shape);
  else
    (void)require_single_valid_shell(shape);
  Bytes payload = to_brep_bytes(shape);
  if (payload.empty())
    throw ValueError("OpenCascade produced an empty BREP snapshot payload");
  return payload;
}

TopoDS_Shape decode_shape(std::string_view payload, RegionRootKind kind) {
  if (payload.empty())
    throw ValueError("BREP snapshot payload is empty");
  const TopoDS_Shape shape = from_brep_bytes(payload);
  const TopAbs_ShapeEnum expected = kind == RegionRootKind::Solid ? TopAbs_SOLID : TopAbs_SHELL;
  if (shape.ShapeType() != expected)
    throw ValueError(std::string("BREP snapshot payload root is not declared ") + std::string(to_string(kind)) +
                     " topology");
  if (kind == RegionRootKind::Solid)
    return require_single_valid_solid(shape);
  return require_single_valid_shell(shape);
}

// ---------------------------------------------------------------------------
// Manifest schema
// ---------------------------------------------------------------------------
namespace {

// Throws unless `value` is an object whose keys are `required` plus any of `optional`.  (It returns
// nothing on purpose: a reference returned from a call that also takes temporaries trips GCC's
// -Wdangling-reference at every use.)
void exact_keys(std::string_view name, const Value& value, const std::set<std::string>& required,
                const std::set<std::string>& optional = {}) {
  if (!value.is_object())
    fail("BREP region snapshot " + std::string(name) + " must be an object");
  std::set<std::string> keys;
  for (const auto& [key, item] : value.as_object())
    keys.insert(key);
  std::vector<std::string> missing, extra;
  for (const std::string& key : required)
    if (keys.count(key) == 0)
      missing.push_back(key);
  for (const std::string& key : keys)
    if (required.count(key) == 0 && optional.count(key) == 0)
      extra.push_back(key);
  if (!missing.empty() || !extra.empty()) {
    std::string details;
    const auto join = [](const std::vector<std::string>& items) {
      std::string out;
      for (std::size_t i = 0; i < items.size(); ++i)
        out += (i ? ", " : "") + items[i];
      return out;
    };
    if (!missing.empty())
      details += "missing " + join(missing);
    if (!extra.empty())
      details += std::string(details.empty() ? "" : "; ") + "unknown " + join(extra);
    fail("BREP region snapshot " + std::string(name) + " schema is invalid: " + details);
  }
}

const Value& at(const Value& object, std::string_view key) {
  return *object.find(key);
}

bool text_equals(const Value& v, std::string_view expected) {
  return v.is_string() && v.as_string() == expected;
}

// "\nOpen CASCADE Topology V4, (c) Open Cascade\nLocations N\nCurve2ds N\n"
bool has_bintools_text_header(std::string_view payload) {
  if (payload.substr(0, kBinToolsV4Preamble.size()) != kBinToolsV4Preamble)
    return false;
  std::size_t at_byte = kBinToolsV4Preamble.size();
  for (const std::string_view label : {std::string_view("Locations "), std::string_view("Curve2ds ")}) {
    if (payload.substr(at_byte, label.size()) != label)
      return false;
    at_byte += label.size();
    const std::size_t digits = at_byte;
    while (at_byte < payload.size() && payload[at_byte] >= '0' && payload[at_byte] <= '9')
      ++at_byte;
    if (at_byte == digits || at_byte >= payload.size() || payload[at_byte] != '\n')
      return false;
    ++at_byte;
  }
  return true;
}

// Returns the validated manifest's root kind and the profile's OCP version.
struct Validated {
  RegionRootKind root_kind;
  std::string ocp_version;
};

Validated validate_manifest(const Value& manifest, std::string_view payload) {
  exact_keys("manifest", manifest,
             {"format", "schema_version", "profile", "coordinate_system", "generator", "source", "region", "shape",
              "provenance"});
  constexpr std::string_view kProfilePrefix = "scadbrep-1-ocp-";
  constexpr std::string_view kProfileSuffix = "-bintools-v4-no-mesh";
  const Value& profile = at(manifest, "profile");
  std::string ocp_version;
  bool profile_ok = text_equals(at(manifest, "format"), "simplecad-brep-region") &&
                    text_equals(at(manifest, "schema_version"), "1.0") && profile.is_string();
  if (profile_ok) {
    const std::string& p = profile.as_string();
    profile_ok = p.size() > kProfilePrefix.size() + kProfileSuffix.size() &&
                 p.compare(0, kProfilePrefix.size(), kProfilePrefix) == 0 &&
                 p.compare(p.size() - kProfileSuffix.size(), kProfileSuffix.size(), kProfileSuffix) == 0;
    if (profile_ok) {
      ocp_version = p.substr(kProfilePrefix.size(), p.size() - kProfilePrefix.size() - kProfileSuffix.size());
      const auto theirs = major_minor(ocp_version);
      const auto ours = major_minor(default_ocp_version());
      profile_ok = theirs.has_value() && ours.has_value() && *theirs == *ours;
    }
  }
  if (!profile_ok)
    fail("BREP region snapshot manifest profile is unsupported");

  const Value& coordinate_system = at(manifest, "coordinate_system");
  exact_keys("coordinate_system", coordinate_system, {"length_unit"});
  if (!text_equals(at(coordinate_system, "length_unit"), "mm"))
    fail("BREP region snapshot length unit must be mm");
  const Value& generator = at(manifest, "generator");
  exact_keys("generator", generator, {"ocp_version"});
  if (!text_equals(at(generator, "ocp_version"), ocp_version))
    fail("BREP region snapshot OCP version does not match this runtime profile");

  const Value& source = at(manifest, "source");
  exact_keys("source", source, {"format", "name", "byte_length", "content_hash", "transferred_root_count"});
  if (!text_equals(at(source, "format"), "step") || !at(source, "name").is_string())
    fail("BREP region snapshot source record is invalid");
  if (!is_count(at(source, "byte_length")) || !is_count(at(source, "transferred_root_count")) ||
      at(source, "transferred_root_count").as_int() < 1)
    fail("BREP region snapshot source counts are invalid");
  if (!is_sha256(at(source, "content_hash")))
    fail("BREP region snapshot source hash is invalid");

  const Value& region = at(manifest, "region");
  exact_keys("region", region, {"kind", "source_face_ids"});
  const Value& region_kind = at(region, "kind");
  if (!text_equals(region_kind, "complete_solid") && !text_equals(region_kind, "face_shell"))
    fail("BREP region snapshot region kind is unsupported");
  const Value& region_ids = at(region, "source_face_ids");
  if (!region_ids.is_array() || !std::all_of(region_ids.as_array().begin(), region_ids.as_array().end(), is_face_id))
    fail("BREP region snapshot source face ids are invalid");
  {
    std::set<std::string> unique;
    for (const Value& id : region_ids.as_array())
      unique.insert(id.as_string());
    if (unique.size() != region_ids.as_array().size())
      fail("BREP region snapshot source face ids are not unique");
  }

  const Value& shape = at(manifest, "shape");
  exact_keys(
      "shape", shape,
      {"root_shape_type", "valid", "solid_count", "shell_count", "face_count", "edge_count", "vertex_count", "encoding",
       "format_version", "triangulation", "normals", "byte_length", "content_hash", "face_fingerprints"},
      {"closed", "volume"});
  const Value& root_value = at(shape, "root_shape_type");
  if (!text_equals(root_value, "shell") && !text_equals(root_value, "solid"))
    fail("BREP region snapshot root shape type is unsupported");
  const bool is_solid = root_value.as_string() == "solid";
  if (region_kind.as_string() != (is_solid ? "complete_solid" : "face_shell"))
    fail("BREP region snapshot region kind and root shape disagree");
  if (!(at(shape, "valid").is_bool() && at(shape, "valid").as_bool()))
    fail("BREP region snapshot must declare a valid shape");
  for (const char* name : {"solid_count", "shell_count", "face_count", "edge_count", "vertex_count", "byte_length"})
    if (!is_count(at(shape, name)))
      fail(std::string("BREP region snapshot ") + name + " is invalid");
  if (at(shape, "face_count").as_int() < 1)
    fail("BREP region snapshot must contain at least one face");
  if (is_solid) {
    if (at(shape, "solid_count").as_int() != 1 || at(shape, "shell_count").as_int() < 1)
      fail("BREP region snapshot solid counts are invalid");
    const Value* volume = shape.find("volume");
    if (shape.find("closed") != nullptr || volume == nullptr || !is_finite_number(*volume) ||
        volume->as_double() <= 0.0)
      fail("BREP region snapshot solid descriptor is invalid");
  } else {
    if (at(shape, "solid_count").as_int() != 0 || at(shape, "shell_count").as_int() != 1)
      fail("BREP region snapshot shell counts are invalid");
    const Value* closed = shape.find("closed");
    if (shape.find("volume") != nullptr || closed == nullptr || !closed->is_bool())
      fail("BREP region snapshot shell descriptor is invalid");
  }
  if (!text_equals(at(shape, "encoding"), "occt-bintools"))
    fail("BREP region snapshot encoding is unsupported");
  if (!(at(shape, "format_version").is_int() && at(shape, "format_version").as_int() == 4))
    fail("BREP region snapshot BinTools version is unsupported");
  if (!(at(shape, "triangulation").is_bool() && !at(shape, "triangulation").as_bool()) ||
      !(at(shape, "normals").is_bool() && !at(shape, "normals").as_bool()))
    fail("BREP region snapshot mesh profile is unsupported");
  if (!is_sha256(at(shape, "content_hash")))
    fail("BREP region snapshot payload hash is invalid");
  if (at(shape, "content_hash").as_string() != sha256_tagged(payload))
    fail("BREP region snapshot payload SHA-256 does not match");
  if (static_cast<std::size_t>(at(shape, "byte_length").as_int()) != payload.size())
    fail("BREP region snapshot payload length does not match");
  if (payload.substr(0, kBinToolsV4Preamble.size()) != kBinToolsV4Preamble)
    fail("BREP region snapshot payload is not BinTools V4");
  if (!has_bintools_text_header(payload))
    fail("BREP region snapshot BinTools text header is invalid");

  const Value& records = at(shape, "face_fingerprints");
  if (!records.is_array() || static_cast<std::int64_t>(records.as_array().size()) != at(shape, "face_count").as_int())
    fail("BREP region snapshot has no face fingerprint records");
  std::vector<std::string> ids;
  for (const Value& record : records.as_array()) {
    exact_keys("face fingerprint", record,
               {"surface_type", "orientation", "area", "centroid", "edge_count", "source_face_id"});
    const Value& surface_type = at(record, "surface_type");
    if (!surface_type.is_string() || surface_type.as_string().empty())
      fail("BREP region snapshot face surface type is invalid");
    const Value& orientation = at(record, "orientation");
    if (!(text_equals(orientation, "TopAbs_FORWARD") || text_equals(orientation, "TopAbs_REVERSED") ||
          text_equals(orientation, "TopAbs_INTERNAL") || text_equals(orientation, "TopAbs_EXTERNAL")))
      fail("BREP region snapshot face orientation is invalid");
    if (!is_finite_number(at(record, "area")) || at(record, "area").as_double() < 0.0)
      fail("BREP region snapshot face area is invalid");
    const Value& centroid = at(record, "centroid");
    if (!centroid.is_array() || centroid.as_array().size() != 3 ||
        !std::all_of(centroid.as_array().begin(), centroid.as_array().end(), is_finite_number))
      fail("BREP region snapshot face centroid is invalid");
    if (!is_count(at(record, "edge_count")))
      fail("BREP region snapshot face edge count is invalid");
    const Value& id = at(record, "source_face_id");
    const auto& allowed = region_ids.as_array();
    if (!id.is_string() || std::find(allowed.begin(), allowed.end(), id) == allowed.end())
      fail("BREP region snapshot face source id is invalid");
    ids.push_back(id.as_string());
  }
  std::vector<std::string> declared;
  for (const Value& id : region_ids.as_array())
    declared.push_back(id.as_string());
  if (ids != declared)
    fail("BREP region snapshot face provenance mapping drifted");

  const Value& provenance = at(manifest, "provenance");
  exact_keys(
      "provenance", provenance,
      {"evidence_origin", "construction", "topology_origin", "runtime_dependency", "target_step_required_at_replay"});
  const Value& replay = at(provenance, "target_step_required_at_replay");
  if (!text_equals(at(provenance, "evidence_origin"), "copied") ||
      !text_equals(at(provenance, "construction"), "exact_transcription") ||
      !text_equals(at(provenance, "topology_origin"), "retained") ||
      !text_equals(at(provenance, "runtime_dependency"), "embedded_target_derived") ||
      !(replay.is_bool() && !replay.as_bool()))
    fail("BREP region snapshot provenance profile is unsupported");
  return {is_solid ? RegionRootKind::Solid : RegionRootKind::Shell, ocp_version};
}

}  // namespace

// ---------------------------------------------------------------------------
// Container encode / decode
// ---------------------------------------------------------------------------
Bytes encode_artifact(const Value& manifest, std::string_view payload) {
  const std::string manifest_bytes = canonical_json(manifest);
  if (manifest_bytes.size() > kBRegionMaxManifestBytes)
    fail("BREP region snapshot manifest exceeds the size limit");
  detail::ByteWriter out;
  out.raw(kBRegionMagic);
  out.u16(kBRegionMajorVersion);
  out.u16(kBRegionMinorVersion);
  out.u32(0);
  out.u64(manifest_bytes.size());
  out.u64(payload.size());
  out.raw(manifest_bytes);
  out.raw(payload);
  Bytes artifact = out.take();
  if (artifact.size() > kBRegionMaxArtifactBytes)
    fail("BREP region snapshot exceeds the size limit");
  return artifact;
}

DecodedRegion decode_artifact(std::string_view bytes, std::optional<RegionRootKind> expected) {
  if (bytes.size() > kBRegionMaxArtifactBytes)
    fail("BREP region snapshot exceeds the size limit");
  if (bytes.size() < kBRegionHeaderSize)
    fail("BREP region snapshot is truncated");
  detail::ByteReader header(bytes, "BREP region snapshot");
  if (header.bytes(kBRegionMagic.size()) != kBRegionMagic)
    fail("BREP region snapshot has invalid magic");
  const std::uint16_t major = header.u16();
  const std::uint16_t minor = header.u16();
  if (major != kBRegionMajorVersion || minor != kBRegionMinorVersion)
    fail("Unsupported BREP region snapshot version: " + std::to_string(major) + "." + std::to_string(minor));
  if (header.u32() != 0)
    fail("BREP region snapshot uses unsupported flags");
  const std::uint64_t manifest_size = header.u64();
  const std::uint64_t payload_size = header.u64();
  if (manifest_size > kBRegionMaxManifestBytes)
    fail("BREP region snapshot manifest exceeds the size limit");
  if (payload_size > kBRegionMaxArtifactBytes || kBRegionHeaderSize + manifest_size + payload_size != bytes.size())
    fail("BREP region snapshot length does not match its header");
  const std::string_view manifest_bytes = bytes.substr(kBRegionHeaderSize, static_cast<std::size_t>(manifest_size));
  const std::string_view payload = bytes.substr(kBRegionHeaderSize + static_cast<std::size_t>(manifest_size));

  Value manifest;
  try {
    manifest = parse_json(manifest_bytes);
    if (canonical_json(manifest) != manifest_bytes)
      fail("JSON bytes are not RFC 8785 canonical");
  } catch (const Error&) {
    throw;
  } catch (const std::exception& e) {
    fail(std::string("BREP region snapshot manifest is not valid canonical JSON: ") + e.what());
  }
  const Validated validated = validate_manifest(manifest, payload);
  if (expected && validated.root_kind != *expected)
    fail(std::string("BREP region snapshot contains ") + std::string(to_string(validated.root_kind)) + ", expected " +
         std::string(to_string(*expected)));
  const Value& shape_record = at(manifest, "shape");

  TopoDS_Shape shape;
  try {
    shape = decode_shape(payload, validated.root_kind);
  } catch (const Error&) {
    throw;
  } catch (const std::exception& e) {
    fail(e.what());
  }
  if (has_triangulation(shape))
    fail("BREP region snapshot payload contains triangulation");
  try {
    if (encode_shape(shape, validated.root_kind).size() != payload.size())
      fail("BREP region snapshot payload has trailing or missing data");
  } catch (const Error&) {
    throw;
  } catch (const std::exception& e) {
    fail(e.what());
  }

  ShapeDescriptor actual;
  try {
    actual = shape_descriptor(shape, validated.root_kind);
  } catch (const std::exception& e) {
    fail(e.what());
  }
  const Value actual_value = actual.to_value();
  for (const char* key : {"root_shape_type", "valid", "solid_count", "shell_count", "face_count", "edge_count",
                          "vertex_count", validated.root_kind == RegionRootKind::Solid ? "volume" : "closed"}) {
    const Value* stored = shape_record.find(key);
    const Value* computed = actual_value.find(key);
    const bool same =
        stored != nullptr && computed != nullptr &&
        ((stored->is_number() && computed->is_number()) ? close_enough(stored->as_double(), computed->as_double())
                                                        : *stored == *computed);
    if (!same)
      fail(std::string("BREP region snapshot shape descriptor drifted at ") + key);
  }

  const Value actual_faces = face_fingerprints(shape);
  const auto& stored_faces = at(shape_record, "face_fingerprints").as_array();
  const auto& computed_faces = actual_faces.as_array();
  bool faces_match = stored_faces.size() == computed_faces.size();
  for (std::size_t i = 0; faces_match && i < stored_faces.size(); ++i) {
    const Value& s = stored_faces[i];
    const Value& c = computed_faces[i];
    faces_match = at(s, "surface_type") == at(c, "surface_type") && at(s, "orientation") == at(c, "orientation") &&
                  at(s, "edge_count") == at(c, "edge_count") &&
                  close_enough(at(s, "area").as_double(), at(c, "area").as_double());
    for (std::size_t k = 0; faces_match && k < 3; ++k)
      faces_match =
          close_enough(at(s, "centroid").as_array()[k].as_double(), at(c, "centroid").as_array()[k].as_double());
  }
  if (!faces_match)
    fail("BREP region snapshot face order or geometry drifted");
  if (static_cast<std::int64_t>(at(at(manifest, "region"), "source_face_ids").size()) != actual.face_count)
    fail("BREP region snapshot source face mapping is incomplete");
  return {shape, std::move(manifest), validated.root_kind};
}

// ---------------------------------------------------------------------------
// Reading a file
// ---------------------------------------------------------------------------
namespace {

namespace fs = std::filesystem;

bool is_link_like(const fs::file_status& status) {
  if (status.type() == fs::file_type::symlink)
    return true;
#if defined(_MSC_VER)
  if (status.type() == fs::file_type::junction)
    return true;  // a Windows reparse point that is not a symlink
#endif
  return false;
}

// Resolves `path` inside `root`, refusing escapes and links.
fs::path resolve_in_root(const fs::path& path, const fs::path& replay_root) {
  std::error_code ec;
  const fs::path root = fs::weakly_canonical(replay_root, ec);
  if (ec)
    fail("Could not resolve the replay working directory: " + path_to_utf8(replay_root));
  const fs::path joined = root / path;
  const fs::path resolved = fs::weakly_canonical(joined, ec);
  if (ec)
    fail("Could not inspect BREP region snapshot: " + path_to_utf8(joined));
  const fs::path relative = resolved.lexically_relative(root);
  if (relative.empty() || *relative.begin() == fs::path("..") || relative.is_absolute())
    fail("BREP region snapshot escapes the replay working directory");
  fs::path current = root;
  for (const fs::path& part : path) {
    current /= part;
    const fs::file_status status = fs::symlink_status(current, ec);
    if (ec)
      fail("Could not inspect BREP region snapshot path component: " + path_to_utf8(current));
    if (is_link_like(status))
      fail("BREP region snapshot path must not contain symbolic links");
  }
  return resolved;
}

}  // namespace

RegionFile read_artifact(const std::filesystem::path& path, std::string_view sha256, RegionRootKind expected,
                         const std::optional<std::filesystem::path>& replay_root) {
  fs::path source = path;
  if (replay_root)
    source = resolve_in_root(path, *replay_root);
  std::error_code ec;
  const fs::file_status status = fs::symlink_status(source, ec);
  if (ec || !fs::exists(status))
    fail("Could not inspect BREP region snapshot: " + path_to_utf8(source));
  if (!fs::is_regular_file(status))
    fail("BREP region snapshot must be a regular file");
  const std::uintmax_t size = fs::file_size(source, ec);
  if (ec)
    fail("Could not inspect BREP region snapshot: " + path_to_utf8(source));
  if (size > kBRegionMaxArtifactBytes)
    fail("BREP region snapshot exceeds the size limit");
  Bytes data;
  try {
    data = read_file(source, kBRegionMaxArtifactBytes);
  } catch (const std::exception& e) {
    fail("Could not open BREP region snapshot: " + path_to_utf8(source) + " (" + e.what() + ")");
  }
  if (data.size() != size)
    fail("BREP region snapshot changed while it was being opened");

  std::string expected_hash(sha256);
  const auto not_space = [](unsigned char c) { return !std::isspace(c); };
  expected_hash.erase(expected_hash.begin(), std::find_if(expected_hash.begin(), expected_hash.end(), not_space));
  expected_hash.erase(std::find_if(expected_hash.rbegin(), expected_hash.rend(), not_space).base(),
                      expected_hash.end());
  std::transform(expected_hash.begin(), expected_hash.end(), expected_hash.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (expected_hash.rfind("sha256:", 0) != 0)
    expected_hash = "sha256:" + expected_hash;
  const std::string actual_hash = sha256_tagged(data);
  if (expected_hash != actual_hash)
    fail("BREP region snapshot SHA-256 mismatch: expected " + expected_hash + ", got " + actual_hash);
  DecodedRegion decoded = decode_artifact(data, expected);
  return {std::move(decoded.shape), std::move(decoded.manifest), actual_hash};
}

// ---------------------------------------------------------------------------
// Creating
// ---------------------------------------------------------------------------
Bytes make_region_artifact(const TopoDS_Shape& shape, RegionRootKind kind, const RegionSource& source,
                           const std::vector<std::string>& source_face_ids, std::string_view ocp_version) {
  const std::string version = ocp_version.empty() ? default_ocp_version() : std::string(ocp_version);
  const Bytes payload = encode_shape(shape, kind);
  Value records = face_fingerprints(shape);
  const std::size_t face_count = records.size();

  std::vector<std::string> ids;
  if (kind == RegionRootKind::Solid) {
    if (!source_face_ids.empty())
      throw ValueError("a complete solid snapshot takes no source_face_ids");
    for (std::size_t i = 0; i < face_count; ++i)
      ids.push_back("face:" + std::to_string(i));
  } else {
    ids = source_face_ids;
    if (ids.size() != face_count)
      throw ValueError("source_face_ids must name every face of the shell, in the shell's face order");
    std::set<std::string> unique(ids.begin(), ids.end());
    if (unique.size() != ids.size())
      throw ValueError("source_face_ids contains duplicates");
    for (const std::string& id : ids)
      if (!is_face_id(Value(id)))
        throw ValueError("source_face_ids must look like 'face:<n>', got '" + id + "'");
  }
  for (std::size_t i = 0; i < face_count; ++i)
    records.as_array()[i].set("source_face_id", ids[i]);

  Value manifest = Value::object();
  manifest.set("format", "simplecad-brep-region");
  manifest.set("schema_version", "1.0");
  manifest.set("profile", region_profile(version));
  Value coordinate_system = Value::object();
  coordinate_system.set("length_unit", "mm");
  manifest.set("coordinate_system", std::move(coordinate_system));
  Value generator = Value::object();
  generator.set("ocp_version", version);
  manifest.set("generator", std::move(generator));
  Value source_record = Value::object();
  source_record.set("format", "step");
  source_record.set("name", source.name);
  source_record.set("byte_length", static_cast<std::int64_t>(source.byte_length));
  source_record.set("content_hash", source.content_hash);
  source_record.set("transferred_root_count", source.transferred_root_count);
  manifest.set("source", std::move(source_record));
  Value region = Value::object();
  region.set("kind", kind == RegionRootKind::Solid ? "complete_solid" : "face_shell");
  Value id_values = Value::array();
  for (const std::string& id : ids)
    id_values.push_back(id);
  region.set("source_face_ids", std::move(id_values));
  manifest.set("region", std::move(region));
  Value shape_record = shape_descriptor(shape, kind).to_value();
  shape_record.set("encoding", "occt-bintools");
  shape_record.set("format_version", 4);
  shape_record.set("triangulation", false);
  shape_record.set("normals", false);
  shape_record.set("byte_length", static_cast<std::int64_t>(payload.size()));
  shape_record.set("content_hash", sha256_tagged(payload));
  shape_record.set("face_fingerprints", std::move(records));
  manifest.set("shape", std::move(shape_record));
  Value provenance = Value::object();
  provenance.set("evidence_origin", "copied");
  provenance.set("construction", "exact_transcription");
  provenance.set("topology_origin", "retained");
  provenance.set("runtime_dependency", "embedded_target_derived");
  provenance.set("target_step_required_at_replay", false);
  manifest.set("provenance", std::move(provenance));

  Bytes artifact = encode_artifact(manifest, payload);
  (void)decode_artifact(artifact);  // the writer proves its own output
  return artifact;
}

std::filesystem::path copy_step_solid_region(const std::filesystem::path& step_path,
                                             const std::filesystem::path& output_path, std::string_view ocp_version) {
  const fs::path source = fs::absolute(step_path);
  const fs::path destination = fs::absolute(output_path);
  std::error_code ec;
  if (fs::equivalent(source, destination, ec))
    throw ValueError("output_path must differ from the source STEP path");
  const std::string source_ext = extension_of(source);
  if (source_ext != "step" && source_ext != "stp")
    throw ValueError("path must end in .step or .stp");
  if (extension_of(destination) != "scadbrep")
    throw ValueError("output_path must end in .scadbrep");
  if (path_to_utf8(source.filename()).find(':') != std::string::npos ||
      path_to_utf8(destination.filename()).find(':') != std::string::npos)
    throw ValueError("snapshot filenames must not contain ':'");
  if (!fs::is_regular_file(source, ec))
    throw ValueError("STEP file not found: " + path_to_utf8(source));
  if (!fs::is_directory(destination.parent_path(), ec))
    throw ValueError("output_path parent does not exist: " + path_to_utf8(destination.parent_path()));
  if (fs::is_symlink(destination, ec))
    throw ValueError("output_path must not be a symbolic link");

  const Bytes step_data = read_file(source);
  const StepReadResult step = read_step_bytes(step_data, path_to_utf8(source.filename()));
  const TopoDS_Solid solid = require_single_valid_solid(step.shape);
  RegionSource record;
  record.name = path_to_utf8(source.filename());
  record.byte_length = step_data.size();
  record.content_hash = sha256_tagged(step_data);
  record.transferred_root_count = step.transferred_roots;
  write_file(destination, make_region_artifact(solid, RegionRootKind::Solid, record, {}, ocp_version));
  return destination;
}

std::string checked_region_path(std::string_view path, bool for_graph) {
  const fs::path source = path_from_utf8(path);
  if (path_to_utf8(source.filename()).find(':') != std::string::npos)
    throw ValueError(".scadbrep filenames must not contain ':'");
  if (for_graph && source.is_absolute())
    throw ValueError(
        "GraphSession requires a relative .scadbrep path so model JSON does not record machine-specific absolute "
        "paths");
  if (for_graph && !source.root_name().empty())
    throw ValueError("GraphSession .scadbrep paths must not contain a drive");
  if (for_graph) {
    for (const fs::path& part : source)
      if (part == "..")
        throw ValueError(".scadbrep paths must not traverse parent directories");
    if (path.find('\\') != std::string_view::npos)
      throw ValueError("GraphSession .scadbrep paths must use '/' separators");
  }
  if (extension_of(source) != "scadbrep")
    throw ValueError("path must end in .scadbrep");
  // pathlib spelling: "." parts and doubled separators disappear, ".." stays.
  fs::path normalized;
  for (const fs::path& part : source)
    if (part != "." && !part.empty())
      normalized /= part;
  if (normalized.empty())
    normalized = ".";
  if (!for_graph)
    return path_to_utf8(normalized);
  const std::u8string generic = normalized.generic_u8string();  // pathlib's as_posix()
  return std::string(reinterpret_cast<const char*>(generic.data()), generic.size());
}

}  // namespace scad::io
