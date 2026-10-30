#include "scad/io/mesh.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>

#include <BRepBuilderAPI_Copy.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <IMeshTools_Parameters.hxx>
#include <Poly_Triangulation.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::io {

namespace {

void require_deflection(double value, const char* name) {
  if (!std::isfinite(value) || value <= 0.0)
    throw ValueError(std::string(name) + " must be a positive finite value");
}

// A topology copy of `shape` with the geometry shared and no triangulation:
// meshing it leaves the caller's shape untouched and is safe to run beside
// other threads reading or meshing the original.
TopoDS_Shape meshed_copy(const TopoDS_Shape& shape, const MeshParameters& p) {
  BRepBuilderAPI_Copy copier(shape, /*copyGeom=*/Standard_False, /*copyMesh=*/Standard_False);
  TopoDS_Shape work = copier.Shape();
  IMeshTools_Parameters parameters;
  parameters.Deflection = p.linear_deflection;
  parameters.Angle = p.angular_deflection;
  parameters.Relative = p.relative;
  parameters.InParallel = p.parallel;
  BRepMesh_IncrementalMesh mesher(work, parameters);
  if (!mesher.IsDone())
    throw KernelError("BRepMesh_IncrementalMesh", "OpenCASCADE failed to tessellate the shape");
  return work;
}

Vec3 normalized_or_zero(const Vec3& v) {
  const double n = v.norm();
  return (n > 0.0 && std::isfinite(n)) ? v / n : Vec3{};
}

// The face's triangulation in world coordinates, wound for the face's orientation.
FaceTessellation extract_face(const TopoDS_Face& face) {
  FaceTessellation out;
  TopLoc_Location location;
  const Handle(Poly_Triangulation) triangulation = BRep_Tool::Triangulation(face, location);
  if (triangulation.IsNull() || triangulation->NbTriangles() == 0)
    return out;
  const gp_Trsf trsf = location.Transformation();
  const bool reversed = face.Orientation() == TopAbs_REVERSED;

  const int node_count = triangulation->NbNodes();
  out.vertices.reserve(static_cast<std::size_t>(node_count));
  for (int i = 1; i <= node_count; ++i)
    out.vertices.push_back(kernel::from_pnt(triangulation->Node(i).Transformed(trsf)));

  out.triangles.reserve(static_cast<std::size_t>(triangulation->NbTriangles()));
  for (int i = 1; i <= triangulation->NbTriangles(); ++i) {
    int a = 0, b = 0, c = 0;
    triangulation->Triangle(i).Get(a, b, c);
    if (reversed)
      std::swap(b, c);
    out.triangles.push_back(
        {static_cast<std::uint32_t>(a - 1), static_cast<std::uint32_t>(b - 1), static_cast<std::uint32_t>(c - 1)});
  }

  if (triangulation->HasNormals()) {
    out.node_normals.reserve(static_cast<std::size_t>(node_count));
    for (int i = 1; i <= node_count; ++i) {
      Vec3 n = kernel::from_dir(triangulation->Normal(i).Transformed(trsf));
      out.node_normals.push_back(reversed ? -n : n);
    }
  }
  return out;
}

Vec3 flat_normal(const FaceTessellation& t, const std::array<std::uint32_t, 3>& tri) {
  const Vec3& origin = t.vertices[tri[0]];
  return normalized_or_zero((t.vertices[tri[1]] - origin).cross(t.vertices[tri[2]] - origin));
}

// Per-node normals for a face: OCCT's when it has them, else the area-weighted
// average of the incident triangle normals (equal to the flat normal on a plane).
std::vector<Vec3> node_normals_of(const FaceTessellation& t) {
  if (!t.node_normals.empty())
    return t.node_normals;
  std::vector<Vec3> sums(t.vertices.size());
  for (const auto& tri : t.triangles) {
    const Vec3& origin = t.vertices[tri[0]];
    const Vec3 weighted = (t.vertices[tri[1]] - origin).cross(t.vertices[tri[2]] - origin);  // |.| = 2 x area
    for (const std::uint32_t index : tri)
      sums[index] += weighted;
  }
  for (Vec3& n : sums)
    n = normalized_or_zero(n);
  return sums;
}

void check_index_range(std::size_t vertices, std::size_t triangles) {
  constexpr std::size_t kLimit = std::numeric_limits<std::uint32_t>::max();
  if (vertices > kLimit || triangles * 3 > kLimit)
    throw ValueError("the mesh is too large for 32-bit indices");
}

}  // namespace

void MeshParameters::validate() const {
  require_deflection(linear_deflection, "linear_deflection");
  require_deflection(angular_deflection, "angular_deflection");
}

std::array<std::array<float, 3>, 2> Mesh::bounds() const noexcept {
  std::array<std::array<float, 3>, 2> box{};
  if (vertices.empty())
    return box;
  box[0] = {vertices[0], vertices[1], vertices[2]};
  box[1] = box[0];
  for (std::size_t i = 3; i + 2 < vertices.size(); i += 3) {
    for (std::size_t k = 0; k < 3; ++k) {
      box[0][k] = std::min(box[0][k], vertices[i + k]);
      box[1][k] = std::max(box[1][k], vertices[i + k]);
    }
  }
  return box;
}

std::vector<std::array<Vec3, 3>> FaceTessellation::corner_normals() const {
  std::vector<std::array<Vec3, 3>> out;
  out.reserve(triangles.size());
  for (const auto& tri : triangles) {
    if (!node_normals.empty()) {
      out.push_back({node_normals[tri[0]], node_normals[tri[1]], node_normals[tri[2]]});
    } else {
      const Vec3 n = flat_normal(*this, tri);
      out.push_back({n, n, n});
    }
  }
  return out;
}

Mesh mesh(const TopoDS_Shape& shape, const MeshParameters& parameters) {
  if (shape.IsNull())
    throw ValueError("cannot mesh a null shape");
  parameters.validate();
  return occt_guard([&] {
    const TopoDS_Shape work = meshed_copy(shape, parameters);
    Mesh out;
    std::uint32_t face_index = 0;
    for (TopExp_Explorer explorer(work, TopAbs_FACE); explorer.More(); explorer.Next(), ++face_index) {
      const FaceTessellation face = extract_face(TopoDS::Face(explorer.Current()));
      FaceRange range;
      range.face_index = face_index;
      range.first_triangle = static_cast<std::uint32_t>(out.triangle_count());
      range.triangle_count = static_cast<std::uint32_t>(face.triangles.size());
      out.face_ranges.push_back(range);
      if (face.triangles.empty())
        continue;

      check_index_range(out.vertex_count() + face.vertices.size(), out.triangle_count() + face.triangles.size());
      const auto offset = static_cast<std::uint32_t>(out.vertex_count());
      const std::vector<Vec3> normals = node_normals_of(face);
      for (std::size_t i = 0; i < face.vertices.size(); ++i) {
        const Vec3& v = face.vertices[i];
        const Vec3& n = normals[i];
        out.vertices.insert(out.vertices.end(),
                            {static_cast<float>(v.x), static_cast<float>(v.y), static_cast<float>(v.z)});
        out.normals.insert(out.normals.end(),
                           {static_cast<float>(n.x), static_cast<float>(n.y), static_cast<float>(n.z)});
      }
      for (const auto& tri : face.triangles) {
        out.triangles.insert(out.triangles.end(), {tri[0] + offset, tri[1] + offset, tri[2] + offset});
        out.face_ids.push_back(face_index);
      }
    }
    return out;
  });
}

FaceTessellation tessellate_face_with_normals(const TopoDS_Face& face, double tolerance, double angular_tolerance) {
  if (face.IsNull())
    throw ValueError("cannot tessellate a null face");
  MeshParameters parameters;
  parameters.linear_deflection = tolerance;
  parameters.angular_deflection = angular_tolerance;
  parameters.parallel = false;
  parameters.validate();
  return occt_guard([&] {
    const TopoDS_Shape work = meshed_copy(face, parameters);
    return extract_face(TopoDS::Face(work));
  });
}

std::array<Vec3, 2> TriMesh::bounds() const noexcept {
  std::array<Vec3, 2> box{};
  if (vertices.empty())
    return box;
  box[0] = box[1] = Vec3{vertices[0], vertices[1], vertices[2]};
  for (std::size_t i = 3; i + 2 < vertices.size(); i += 3) {
    box[0] = {std::min(box[0].x, vertices[i]), std::min(box[0].y, vertices[i + 1]),
              std::min(box[0].z, vertices[i + 2])};
    box[1] = {std::max(box[1].x, vertices[i]), std::max(box[1].y, vertices[i + 1]),
              std::max(box[1].z, vertices[i + 2])};
  }
  return box;
}

TriMesh build_solid_trimesh(const Shape& solid, double linear_tolerance, double angular_tolerance) {
  MeshParameters parameters;
  parameters.linear_deflection = linear_tolerance;
  parameters.angular_deflection = angular_tolerance;
  parameters.validate();
  if (solid.wrapped().IsNull())
    throw ValueError("cannot mesh a null shape");
  return occt_guard([&] {
    const TopoDS_Shape work = meshed_copy(solid.wrapped(), parameters);
    TriMesh out;
    out.linear_tolerance = linear_tolerance;
    out.angular_tolerance = angular_tolerance;
    TopExp_Explorer original(solid.wrapped(), TopAbs_FACE);
    std::int64_t face_index = 0;
    for (TopExp_Explorer explorer(work, TopAbs_FACE); explorer.More(); explorer.Next(), original.Next(), ++face_index) {
      const FaceTessellation face = extract_face(TopoDS::Face(explorer.Current()));
      FaceTriangleRange range;
      range.face_index = face_index;
      range.start = static_cast<std::int64_t>(out.triangle_count());
      range.count = static_cast<std::int64_t>(face.triangles.size());
      range.source_topo_id = solid.sub(original.Current()).topo_id();
      out.face_triangle_ranges.push_back(std::move(range));

      const auto offset = static_cast<std::int64_t>(out.vertex_count());
      for (const Vec3& v : face.vertices)
        out.vertices.insert(out.vertices.end(), {v.x, v.y, v.z});
      for (const auto& tri : face.triangles)
        out.triangles.insert(out.triangles.end(), {tri[0] + offset, tri[1] + offset, tri[2] + offset});
      for (const auto& corners : face.corner_normals())
        for (const Vec3& n : corners)
          out.corner_normals.insert(out.corner_normals.end(), {n.x, n.y, n.z});
    }
    return out;
  });
}

// ---------------------------------------------------------------------------
// Welded mesh
// ---------------------------------------------------------------------------
namespace {

struct GridKey {
  std::int64_t x, y, z;
  bool operator==(const GridKey& o) const noexcept { return x == o.x && y == o.y && z == o.z; }
};
struct GridKeyHash {
  std::size_t operator()(const GridKey& k) const noexcept {
    std::uint64_t h = 1469598103934665603ULL;
    for (const std::int64_t v : {k.x, k.y, k.z}) {
      h ^= static_cast<std::uint64_t>(v);
      h *= 1099511628211ULL;
    }
    return static_cast<std::size_t>(h);
  }
};

std::int64_t quantize(double value, double tolerance) {
  const double q = std::nearbyint(value / tolerance);  // round-half-to-even, like Python's round()
  if (!(std::fabs(q) < 9.0e18))
    throw RuntimeError("OpenCASCADE produced a mesh vertex outside the weldable range");
  return static_cast<std::int64_t>(q);
}

bool collapsed(const std::vector<double>& v, const std::array<std::int32_t, 3>& t) {
  const auto at = [&](int k) {
    return Vec3{v[static_cast<std::size_t>(t[static_cast<std::size_t>(k)]) * 3],
                v[static_cast<std::size_t>(t[static_cast<std::size_t>(k)]) * 3 + 1],
                v[static_cast<std::size_t>(t[static_cast<std::size_t>(k)]) * 3 + 2]};
  };
  const Vec3 p0 = at(0), p1 = at(1), p2 = at(2);
  const Vec3 first = p1 - p0, second = p2 - p0, third = p2 - p1;
  const double max_edge_squared = std::max({first.dot(first), second.dot(second), third.dot(third)});
  if (max_edge_squared == 0.0)
    return true;
  const Vec3 normal = first.cross(second);
  const double area_squared = normal.dot(normal);
  const double eps = std::numeric_limits<double>::epsilon();
  return area_squared <= eps * eps * max_edge_squared * max_edge_squared;
}

}  // namespace

WeldedMesh tessellate_solid(const TopoDS_Shape& solid, const SurfaceMeshParameters& parameters) {
  require_deflection(parameters.linear_deflection, "linear_deflection");
  if (!std::isfinite(parameters.angular_deflection_degrees) || parameters.angular_deflection_degrees <= 0.0 ||
      parameters.angular_deflection_degrees > 180.0)
    throw ValueError("angular_deflection_degrees must be in (0, 180]");
  if (solid.IsNull())
    throw ValueError("cannot mesh a null shape");

  MeshParameters mesher;
  mesher.linear_deflection = parameters.linear_deflection;
  mesher.angular_deflection = parameters.angular_deflection_degrees * kPi / 180.0;
  mesher.relative = parameters.relative;
  mesher.parallel = false;

  return occt_guard([&] {
    const TopoDS_Shape work = meshed_copy(solid, mesher);
    const double weld = std::max(std::min(parameters.linear_deflection * 1.0e-7, 1.0e-7), 1.0e-9);
    WeldedMesh out;
    std::unordered_map<GridKey, std::int32_t, GridKeyHash> index_of;
    std::vector<std::int32_t> local;
    for (TopExp_Explorer explorer(work, TopAbs_FACE); explorer.More(); explorer.Next()) {
      const FaceTessellation face = extract_face(TopoDS::Face(explorer.Current()));
      if (face.triangles.empty())
        throw RuntimeError("OpenCASCADE produced an empty face triangulation");
      local.assign(face.vertices.size(), 0);
      for (std::size_t i = 0; i < face.vertices.size(); ++i) {
        const Vec3& p = face.vertices[i];
        if (!p.is_finite())
          throw RuntimeError("OpenCASCADE produced a non-finite mesh vertex");
        const GridKey key{quantize(p.x, weld), quantize(p.y, weld), quantize(p.z, weld)};
        const auto [slot, inserted] = index_of.try_emplace(key, static_cast<std::int32_t>(out.vertex_count()));
        if (inserted)
          out.vertices.insert(out.vertices.end(), {p.x, p.y, p.z});
        local[i] = slot->second;
      }
      for (const auto& tri : face.triangles) {
        const std::array<std::int32_t, 3> indices{local[tri[0]], local[tri[1]], local[tri[2]]};
        if (indices[0] == indices[1] || indices[1] == indices[2] || indices[0] == indices[2])
          continue;
        if (!collapsed(out.vertices, indices))
          out.triangles.push_back(indices);
      }
    }
    if (out.vertices.empty() || out.triangles.empty())
      throw RuntimeError("OpenCASCADE produced no surface triangles");
    return out;
  });
}

}  // namespace scad::io
