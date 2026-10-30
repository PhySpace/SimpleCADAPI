// STL, OBJ and GLB: the mesh formats.
#include <algorithm>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstring>
#include <unordered_map>

#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepLib.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Shell.hxx>
#include <gp_Pnt.hxx>

#include "bytes.hpp"
#include "numfmt.hpp"
#include "scad/core/error.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/json.hpp"
#include "scad/kernel/topology.hpp"

namespace scad::io {

namespace {

const ErrorSpec& export_stl_spec() {
  static const ErrorSpec spec{
      "export_stl",
      "Failed to export the shapes as STL.",
      {"The shapes are empty, null, or cannot be tessellated by OpenCASCADE.",
       "linear_deflection or angular_deflection_degrees is out of range.", "The destination is not writable."},
      {"Pass valid solids.", "Use a positive linear_deflection and an angular deflection in (0, 180].",
       "Write to a directory that exists and is writable."}};
  return spec;
}

const ErrorSpec& export_stl_shape_spec() {
  static const ErrorSpec spec{"export_stl_shape",
                              "Failed to export the shape as STL.",
                              {"The shape is null or cannot be tessellated.", "The destination is not writable."},
                              {"Pass a valid shape.", "Write to a directory that exists and is writable."}};
  return spec;
}

const ErrorSpec& import_stl_spec() {
  static const ErrorSpec spec{
      "import_stl",
      "Failed to read the STL file.",
      {"The file does not exist or is not binary or ASCII STL.", "The file is truncated or holds no triangles."},
      {"Check the path and the file's origin.", "Re-export the model as STL."}};
  return spec;
}

const ErrorSpec& export_obj_spec() {
  static const ErrorSpec spec{
      "export_obj",
      "Failed to export the shapes as OBJ.",
      {"The shapes are empty, null, or cannot be tessellated by OpenCASCADE.",
       "linear_deflection or angular_deflection_degrees is out of range.", "The destination is not writable."},
      {"Pass valid solids.", "Use a positive linear_deflection and an angular deflection in (0, 180].",
       "Write to a directory that exists and is writable."}};
  return spec;
}

const ErrorSpec& export_glb_spec() {
  static const ErrorSpec spec{
      "export_glb",
      "Failed to export the shapes as GLB.",
      {"The shapes are empty, null, or cannot be tessellated by OpenCASCADE.", "The destination is not writable."},
      {"Pass valid shapes.", "Write to a directory that exists and is writable."}};
  return spec;
}

void put_le32(std::string& out, std::uint32_t v) {
  for (int shift = 0; shift < 32; shift += 8)
    out.push_back(static_cast<char>((v >> shift) & 0xFF));
}
void put_le_float(std::string& out, float v) {
  put_le32(out, std::bit_cast<std::uint32_t>(v));
}

std::uint32_t get_le32(std::string_view bytes, std::size_t at) {
  std::uint32_t v = 0;
  for (std::size_t i = 0; i < 4; ++i)
    v |= static_cast<std::uint32_t>(static_cast<unsigned char>(bytes[at + i])) << (8 * i);
  return v;
}
float get_le_float(std::string_view bytes, std::size_t at) {
  return std::bit_cast<float>(get_le32(bytes, at));
}

Vec3 point_of(const std::vector<double>& v, std::int32_t index) {
  const auto i = static_cast<std::size_t>(index) * 3;
  return {v[i], v[i + 1], v[i + 2]};
}

std::string scientific(double value) {
  char buffer[64];
  const auto result = std::to_chars(buffer, buffer + sizeof buffer, value, std::chars_format::scientific, 8);
  return std::string(buffer, result.ptr);
}

Vec3 facet_normal(const Vec3& a, const Vec3& b, const Vec3& c) {
  const Vec3 n = (b - a).cross(c - a);
  const double length = n.norm();
  return length > 0.0 && std::isfinite(length) ? n / length : Vec3{};
}

}  // namespace

// ---------------------------------------------------------------------------
// Surface tessellation of whole shape lists
// ---------------------------------------------------------------------------
std::vector<TopoDS_Shape> surface_solids(const TopoDS_Shape& shape) {
  if (shape.IsNull())
    throw ValueError("cannot mesh a null shape");
  std::vector<TopoDS_Shape> solids;
  for (const TopoDS_Solid& solid : kernel::solids_of(shape))
    solids.push_back(solid);
  if (solids.empty())
    solids.push_back(shape);  // a shell or face still has a surface to mesh
  return solids;
}

WeldedMesh tessellate_surface(const std::vector<TopoDS_Shape>& shapes, const SurfaceMeshParameters& parameters,
                              std::size_t* solid_count) {
  if (shapes.empty())
    throw ValueError("No shapes to export");
  WeldedMesh merged;
  std::size_t solids = 0;
  for (const TopoDS_Shape& shape : shapes) {
    for (const TopoDS_Shape& solid : surface_solids(shape)) {
      const WeldedMesh part = tessellate_solid(solid, parameters);
      const auto offset = static_cast<std::int32_t>(merged.vertex_count());
      merged.vertices.insert(merged.vertices.end(), part.vertices.begin(), part.vertices.end());
      for (const auto& t : part.triangles)
        merged.triangles.push_back({t[0] + offset, t[1] + offset, t[2] + offset});
      ++solids;
    }
  }
  if (solid_count != nullptr)
    *solid_count = solids;
  return merged;
}

namespace {

SurfaceExportReport surface_report(const std::filesystem::path& path, const WeldedMesh& mesh, std::size_t solids,
                                   const SurfaceMeshParameters& parameters) {
  SurfaceExportReport report;
  report.output_path = path;
  report.solid_count = solids;
  report.vertex_count = mesh.vertex_count();
  report.triangle_count = mesh.triangles.size();
  report.parameters = parameters;
  return report;
}

}  // namespace

// ---------------------------------------------------------------------------
// STL
// ---------------------------------------------------------------------------
Bytes binary_stl_bytes(const WeldedMesh& mesh) {
  constexpr std::string_view kHeaderText = "SimpleCAD OpenCASCADE BREP tessellation";
  Bytes out;
  out.reserve(84 + 50 * mesh.triangles.size());
  out.append(kHeaderText);
  out.append(80 - kHeaderText.size(), '\0');
  put_le32(out, static_cast<std::uint32_t>(mesh.triangles.size()));
  for (const auto& t : mesh.triangles) {
    const Vec3 a = point_of(mesh.vertices, t[0]), b = point_of(mesh.vertices, t[1]), c = point_of(mesh.vertices, t[2]);
    const Vec3 n = (b - a).cross(c - a);
    const double length = n.norm();
    if (length == 0.0 || !std::isfinite(length))
      throw RuntimeError("STL tessellation contains a collapsed triangle");
    const Vec3 unit = n / length;
    for (const double v : {unit.x, unit.y, unit.z})
      put_le_float(out, static_cast<float>(v));
    for (const Vec3& p : {a, b, c})
      for (const double v : {p.x, p.y, p.z})
        put_le_float(out, static_cast<float>(v));
    out.append(2, '\0');
  }
  return out;
}

SurfaceExportReport export_stl(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                               const SurfaceMeshParameters& parameters) {
  return guarded(export_stl_spec(), [&] {
    std::size_t solids = 0;
    const WeldedMesh mesh = occt_guard([&] { return tessellate_surface(shapes, parameters, &solids); });
    write_file(path, binary_stl_bytes(mesh));
    return surface_report(path, mesh, solids, parameters);
  });
}

namespace {

void write_ascii_stl(const Mesh& m, const std::filesystem::path& path) {
  AtomicWriter writer(path);
  std::ostream& out = writer.stream();
  out << "solid scad\n";
  const auto vertex = [&](std::uint32_t index) {
    const std::size_t i = static_cast<std::size_t>(index) * 3;
    return Vec3{static_cast<double>(m.vertices[i]), static_cast<double>(m.vertices[i + 1]),
                static_cast<double>(m.vertices[i + 2])};
  };
  for (std::size_t t = 0; t < m.triangle_count(); ++t) {
    const Vec3 a = vertex(m.triangles[3 * t]), b = vertex(m.triangles[3 * t + 1]), c = vertex(m.triangles[3 * t + 2]);
    const Vec3 n = facet_normal(a, b, c);
    out << " facet normal " << scientific(n.x) << ' ' << scientific(n.y) << ' ' << scientific(n.z)
        << "\n  outer loop\n";
    for (const Vec3& p : {a, b, c})
      out << "   vertex " << scientific(p.x) << ' ' << scientific(p.y) << ' ' << scientific(p.z) << '\n';
    out << "  endloop\n endfacet\n";
  }
  out << "endsolid scad\n";
  writer.commit();
}

}  // namespace

void export_stl_ascii(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                      const MeshParameters& parameters) {
  guarded(export_stl_shape_spec(), [&] {
    const Mesh m = mesh(make_compound(shapes), parameters);
    if (m.empty())
      throw ValueError("STL write failed: the shapes have no triangulated faces");
    write_ascii_stl(m, path);
  });
}

void export_stl_shape(const TopoDS_Shape& shape, const std::filesystem::path& path) {
  MeshParameters parameters;
  parameters.linear_deflection = 0.1;
  parameters.angular_deflection = 0.5;  // BRepMesh_IncrementalMesh's default
  parameters.parallel = false;
  export_stl_ascii({shape}, path, parameters);
}

namespace {

struct BitKey {
  std::uint32_t x, y, z;
  bool operator==(const BitKey& o) const noexcept { return x == o.x && y == o.y && z == o.z; }
};
struct BitKeyHash {
  std::size_t operator()(const BitKey& k) const noexcept {
    std::uint64_t h = 1469598103934665603ULL;
    for (const std::uint32_t v : {k.x, k.y, k.z}) {
      h ^= v;
      h *= 1099511628211ULL;
    }
    return static_cast<std::size_t>(h);
  }
};

std::uint32_t bits_of(float v) {
  return v == 0.0F ? 0U : std::bit_cast<std::uint32_t>(v);
}  // fold -0.0 into 0.0

// Triangle soup (9 floats per triangle) -> indexed mesh.
Mesh index_soup(const std::vector<float>& soup) {
  Mesh mesh;
  std::unordered_map<BitKey, std::uint32_t, BitKeyHash> index_of;
  const std::size_t triangles = soup.size() / 9;
  mesh.triangles.reserve(triangles * 3);
  std::vector<std::uint32_t> kept;
  for (std::size_t t = 0; t < triangles; ++t) {
    std::uint32_t ids[3];
    for (std::size_t k = 0; k < 3; ++k) {
      const float* p = &soup[t * 9 + k * 3];
      const BitKey key{bits_of(p[0]), bits_of(p[1]), bits_of(p[2])};
      const auto [slot, inserted] = index_of.try_emplace(key, static_cast<std::uint32_t>(mesh.vertex_count()));
      if (inserted)
        mesh.vertices.insert(mesh.vertices.end(), {p[0], p[1], p[2]});
      ids[k] = slot->second;
    }
    if (ids[0] == ids[1] || ids[1] == ids[2] || ids[0] == ids[2])
      continue;  // zero area
    mesh.triangles.insert(mesh.triangles.end(), {ids[0], ids[1], ids[2]});
  }
  // Area-weighted vertex normals.
  std::vector<Vec3> sums(mesh.vertex_count());
  const auto at = [&](std::uint32_t i) {
    return Vec3{static_cast<double>(mesh.vertices[i * 3]), static_cast<double>(mesh.vertices[i * 3 + 1]),
                static_cast<double>(mesh.vertices[i * 3 + 2])};
  };
  for (std::size_t t = 0; t < mesh.triangle_count(); ++t) {
    const std::uint32_t a = mesh.triangles[3 * t], b = mesh.triangles[3 * t + 1], c = mesh.triangles[3 * t + 2];
    const Vec3 weighted = (at(b) - at(a)).cross(at(c) - at(a));
    sums[a] += weighted;
    sums[b] += weighted;
    sums[c] += weighted;
  }
  mesh.normals.reserve(sums.size() * 3);
  for (const Vec3& s : sums) {
    const Vec3 n = s.normalized();
    mesh.normals.insert(mesh.normals.end(),
                        {static_cast<float>(n.x), static_cast<float>(n.y), static_cast<float>(n.z)});
  }
  mesh.face_ids.assign(mesh.triangle_count(), 0);
  mesh.face_ranges.push_back({0, 0, static_cast<std::uint32_t>(mesh.triangle_count())});
  return mesh;
}

bool is_space(char c) {
  return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f' || c == '\v';
}

std::vector<float> parse_ascii_stl(std::string_view text) {
  std::vector<float> soup;
  std::size_t pos = 0;
  const auto next_token = [&]() -> std::string_view {
    while (pos < text.size() && is_space(text[pos]))
      ++pos;
    const std::size_t begin = pos;
    while (pos < text.size() && !is_space(text[pos]))
      ++pos;
    return text.substr(begin, pos - begin);
  };
  std::size_t vertices_in_facet = 0;
  for (std::string_view token = next_token(); !token.empty(); token = next_token()) {
    if (token == "vertex") {
      for (int k = 0; k < 3; ++k) {
        const std::string_view number = next_token();
        double value = 0.0;
        if (!detail::parse_double(number, value))
          throw ValueError("ASCII STL has a malformed vertex coordinate '" + std::string(number) + "'");
        soup.push_back(static_cast<float>(value));
      }
      ++vertices_in_facet;
    } else if (token == "endfacet") {
      if (vertices_in_facet != 3)
        throw ValueError("ASCII STL has a facet without exactly three vertices");
      vertices_in_facet = 0;
    }
  }
  if (vertices_in_facet != 0)
    throw ValueError("ASCII STL ends inside a facet");
  return soup;
}

}  // namespace

Mesh read_stl_bytes(std::string_view bytes) {
  return guarded(import_stl_spec(), [&] {
    std::vector<float> soup;
    const bool binary_size_matches =
        bytes.size() >= 84 && bytes.size() == 84 + static_cast<std::size_t>(get_le32(bytes, 80)) * 50;
    if (binary_size_matches) {
      const std::size_t count = get_le32(bytes, 80);
      soup.reserve(count * 9);
      for (std::size_t t = 0; t < count; ++t) {
        const std::size_t base = 84 + t * 50 + 12;  // skip the stored normal: it is recomputed from the vertices
        for (std::size_t k = 0; k < 9; ++k) {
          const float v = get_le_float(bytes, base + k * 4);
          if (!std::isfinite(v))
            throw ValueError("binary STL holds a non-finite coordinate");
          soup.push_back(v);
        }
      }
    } else if (bytes.substr(0, 5) == "solid" || bytes.find("facet") != std::string_view::npos) {
      soup = parse_ascii_stl(bytes);
    } else {
      throw ValueError("the bytes are neither binary nor ASCII STL");
    }
    if (soup.empty())
      throw ValueError("the STL holds no triangles");
    Mesh mesh = index_soup(soup);
    if (mesh.empty())
      throw ValueError("the STL holds only degenerate triangles");
    return mesh;
  });
}

Mesh read_stl(const std::filesystem::path& path) {
  return guarded(import_stl_spec(), [&] { return read_stl_bytes(read_file(path)); });
}

TopoDS_Shape stl_to_shape(const Mesh& mesh, double sewing_tolerance) {
  if (mesh.empty())
    throw ValueError("cannot build a shape from an empty mesh");
  if (!std::isfinite(sewing_tolerance) || sewing_tolerance <= 0.0)
    throw ValueError("sewing_tolerance must be a positive finite value");
  return occt_guard([&]() -> TopoDS_Shape {
    BRepBuilderAPI_Sewing sewing(sewing_tolerance);
    const auto point = [&](std::uint32_t i) {
      return gp_Pnt(static_cast<double>(mesh.vertices[i * 3]), static_cast<double>(mesh.vertices[i * 3 + 1]),
                    static_cast<double>(mesh.vertices[i * 3 + 2]));
    };
    std::size_t added = 0;
    for (std::size_t t = 0; t < mesh.triangle_count(); ++t) {
      BRepBuilderAPI_MakePolygon polygon(point(mesh.triangles[3 * t]), point(mesh.triangles[3 * t + 1]),
                                         point(mesh.triangles[3 * t + 2]), /*Close=*/Standard_True);
      if (!polygon.IsDone())
        continue;
      BRepBuilderAPI_MakeFace face(polygon.Wire(), /*OnlyPlane=*/Standard_True);
      if (!face.IsDone())
        continue;
      sewing.Add(face.Face());
      ++added;
    }
    if (added == 0)
      throw ValueError("every triangle of the mesh is degenerate");
    sewing.Perform();
    TopoDS_Shape sewn = sewing.SewedShape();
    if (sewn.IsNull())
      throw RuntimeError("OpenCASCADE could not sew the triangles");

    std::vector<TopoDS_Shell> shells;
    for (TopExp_Explorer explorer(sewn, TopAbs_SHELL); explorer.More(); explorer.Next())
      shells.push_back(TopoDS::Shell(explorer.Current()));
    if (shells.size() == 1 && BRep_Tool::IsClosed(shells.front())) {
      BRepBuilderAPI_MakeSolid maker(shells.front());
      if (maker.IsDone()) {
        TopoDS_Solid solid = maker.Solid();
        BRepLib::OrientClosedSolid(solid);
        return solid;
      }
    }
    return sewn;
  });
}

Shape import_stl_shape(const std::filesystem::path& path, double sewing_tolerance) {
  return guarded(import_stl_spec(), [&] { return Shape::from_occt(stl_to_shape(read_stl(path), sewing_tolerance)); });
}

// ---------------------------------------------------------------------------
// OBJ
// ---------------------------------------------------------------------------
Bytes obj_bytes(const WeldedMesh& mesh) {
  Bytes out = "# SimpleCAD OpenCASCADE BREP tessellation\n";
  for (std::size_t i = 0; i < mesh.vertex_count(); ++i) {
    out += "v " + detail::format_general(mesh.vertices[3 * i], 17) + ' ' +
           detail::format_general(mesh.vertices[3 * i + 1], 17) + ' ' +
           detail::format_general(mesh.vertices[3 * i + 2], 17) + '\n';
  }
  for (const auto& t : mesh.triangles)
    out += "f " + std::to_string(t[0] + 1) + ' ' + std::to_string(t[1] + 1) + ' ' + std::to_string(t[2] + 1) + '\n';
  return out;
}

SurfaceExportReport export_obj(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                               const SurfaceMeshParameters& parameters) {
  return guarded(export_obj_spec(), [&] {
    std::size_t solids = 0;
    const WeldedMesh mesh = occt_guard([&] { return tessellate_surface(shapes, parameters, &solids); });
    write_file(path, obj_bytes(mesh));
    return surface_report(path, mesh, solids, parameters);
  });
}

// ---------------------------------------------------------------------------
// GLB
// ---------------------------------------------------------------------------
namespace {

Value glb_accessor(std::int64_t view, std::int64_t component, std::int64_t count, const char* type) {
  Value a = Value::object();
  a.set("bufferView", view);
  a.set("componentType", component);
  a.set("count", count);
  a.set("type", type);
  return a;
}

Value glb_view(std::size_t offset, std::size_t length, std::int64_t target) {
  Value v = Value::object();
  v.set("buffer", 0);
  v.set("byteOffset", static_cast<std::int64_t>(offset));
  v.set("byteLength", static_cast<std::int64_t>(length));
  v.set("target", target);
  return v;
}

Value float_triple(const std::array<float, 3>& v) {
  Value a = Value::array();
  for (const float f : v)
    a.push_back(static_cast<double>(f));
  return a;
}

// glTF component types: 5125 = UNSIGNED_INT (indices), 5126 = FLOAT; buffer targets: 34963 = ELEMENT_ARRAY_BUFFER,
// 34962 = ARRAY_BUFFER. POSITION carries the min/max bounds the spec requires.
Value glb_accessors(const Mesh& mesh) {
  const auto box = mesh.bounds();
  const auto index_count = static_cast<std::int64_t>(mesh.triangles.size());
  const auto vertex_count = static_cast<std::int64_t>(mesh.vertex_count());
  Value accessors = Value::array();
  accessors.push_back(glb_accessor(0, 5125, index_count, "SCALAR"));
  Value positions = glb_accessor(1, 5126, vertex_count, "VEC3");
  positions.set("min", float_triple(box[0]));
  positions.set("max", float_triple(box[1]));
  accessors.push_back(std::move(positions));
  accessors.push_back(glb_accessor(2, 5126, vertex_count, "VEC3"));
  return accessors;
}

Value glb_buffer_views(std::size_t index_bytes, std::size_t position_bytes, std::size_t normal_bytes) {
  Value views = Value::array();
  views.push_back(glb_view(0, index_bytes, 34963));
  views.push_back(glb_view(index_bytes, position_bytes, 34962));
  views.push_back(glb_view(index_bytes + position_bytes, normal_bytes, 34962));
  return views;
}

// The glTF JSON chunk (canonical form, space-padded to 4 bytes): one mesh, one primitive, three
// accessors over three bufferViews of a single buffer laid out as indices | positions | normals.
std::string glb_json(const Mesh& mesh, std::size_t index_bytes, std::size_t position_bytes, std::size_t normal_bytes,
                     std::size_t total) {
  Value accessors = glb_accessors(mesh);
  Value views = glb_buffer_views(index_bytes, position_bytes, normal_bytes);

  Value ranges = Value::array();
  for (const FaceRange& r : mesh.face_ranges) {
    Value item = Value::array();
    item.push_back(static_cast<std::int64_t>(r.first_triangle));
    item.push_back(static_cast<std::int64_t>(r.triangle_count));
    ranges.push_back(std::move(item));
  }
  Value extras = Value::object();
  extras.set("face_triangle_ranges", std::move(ranges));
  Value attributes = Value::object();
  attributes.set("POSITION", 1);
  attributes.set("NORMAL", 2);
  Value primitive = Value::object();
  primitive.set("attributes", std::move(attributes));
  primitive.set("indices", 0);
  primitive.set("mode", 4);
  primitive.set("extras", std::move(extras));
  Value primitives = Value::array();
  primitives.push_back(std::move(primitive));
  Value mesh_entry = Value::object();
  mesh_entry.set("primitives", std::move(primitives));
  Value meshes = Value::array();
  meshes.push_back(std::move(mesh_entry));
  Value node = Value::object();
  node.set("mesh", 0);
  Value nodes = Value::array();
  nodes.push_back(std::move(node));
  Value scene = Value::object();
  Value scene_nodes = Value::array();
  scene_nodes.push_back(0);
  scene.set("nodes", std::move(scene_nodes));
  Value scenes = Value::array();
  scenes.push_back(std::move(scene));
  Value asset = Value::object();
  asset.set("version", "2.0");
  asset.set("generator", "simplecadapi-cpp");
  Value buffer = Value::object();
  buffer.set("byteLength", static_cast<std::int64_t>(total));
  Value buffers = Value::array();
  buffers.push_back(std::move(buffer));

  Value root = Value::object();
  root.set("asset", std::move(asset));
  root.set("scene", 0);
  root.set("scenes", std::move(scenes));
  root.set("nodes", std::move(nodes));
  root.set("meshes", std::move(meshes));
  root.set("accessors", std::move(accessors));
  root.set("bufferViews", std::move(views));
  root.set("buffers", std::move(buffers));

  std::string json = canonical_json(root);
  while (json.size() % 4 != 0)
    json.push_back(' ');
  return json;
}

// The BIN chunk: little-endian indices, then positions, then normals (the order glb_json declares).
std::string glb_binary(const Mesh& mesh, std::size_t total) {
  std::string bin;
  bin.reserve(total);
  for (const std::uint32_t i : mesh.triangles)
    put_le32(bin, i);
  for (const float v : mesh.vertices)
    put_le_float(bin, v);
  for (const float v : mesh.normals)
    put_le_float(bin, v);
  return bin;
}

}  // namespace

Bytes glb_bytes(const Mesh& mesh) {
  if (mesh.empty())
    throw ValueError("cannot export an empty mesh");
  const std::size_t index_bytes = mesh.triangles.size() * 4;
  const std::size_t position_bytes = mesh.vertices.size() * 4;
  const std::size_t normal_bytes = mesh.normals.size() * 4;
  const std::size_t total = index_bytes + position_bytes + normal_bytes;  // every part is a multiple of 4

  const std::string json = glb_json(mesh, index_bytes, position_bytes, normal_bytes, total);
  const std::string bin = glb_binary(mesh, total);

  Bytes out;
  out.reserve(12 + 8 + json.size() + 8 + bin.size());
  put_le32(out, 0x46546C67U);  // "glTF"
  put_le32(out, 2);
  put_le32(out, static_cast<std::uint32_t>(12 + 8 + json.size() + 8 + bin.size()));
  put_le32(out, static_cast<std::uint32_t>(json.size()));
  put_le32(out, 0x4E4F534AU);  // "JSON"
  out += json;
  put_le32(out, static_cast<std::uint32_t>(bin.size()));
  put_le32(out, 0x004E4942U);  // "BIN\0"
  out += bin;
  return out;
}

void export_glb(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                const MeshParameters& parameters) {
  guarded(export_glb_spec(), [&] {
    const TopoDS_Shape shape = make_compound(shapes);
    write_file(path, glb_bytes(mesh(shape, parameters)));
  });
}

}  // namespace scad::io
