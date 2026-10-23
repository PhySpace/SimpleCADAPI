// Tessellation.
//
// Three layers, from what most callers want to what the Python SDK's internals
// need:
//
//  1. mesh(): the whole shape once, float32 arrays ready for numpy/GPU
//     (vertices, per-vertex normals, triangles, per-triangle face ids).
//  2. build_solid_trimesh() / cached_mesh(): the double-precision TriMesh with
//     per-corner normals and per-face triangle ranges of
//     simplecadapi/_internal/mesh.py.
//  3. tessellate_face_with_normals(): kernel/ocp_mesh.py, one face at a time.
//
// The tessellation itself (BRepMesh_IncrementalMesh) runs on a *topology copy*
// of the input: the geometry is shared, nothing is attached to the caller's
// shape.  Two threads can therefore mesh the same shape at the same time, and
// meshing a shape never changes what an export of it later produces.
//
// Vertices are not shared between faces (each face keeps its own nodes), so the
// normals stay sharp across CAD edges.  Triangles wind counter-clockwise seen
// from outside the solid (faces that the solid uses reversed are flipped).
//
// face_ids index the faces in TopExp_Explorer order -- the order of
// `solid.faces()` -- which for a valid solid or shell is also the order of
// TopExp::MapShapes, hence `face_<id>` is the face's topo_id.
#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/core/vec.hpp"
#include "scad/topo/shape.hpp"

namespace scad::io {

inline constexpr double kDefaultLinearDeflection = 0.35;   // kernel/ocp_mesh.py tessellate_face
inline constexpr double kDefaultAngularDeflection = 0.22;  // radians

struct MeshParameters {
  double linear_deflection = kDefaultLinearDeflection;
  double angular_deflection = kDefaultAngularDeflection;  // radians
  // Interpret linear_deflection as a fraction of each edge's / face's size.
  bool relative = false;
  // Mesh faces on OCCT's thread pool.  Safe on a private copy; costs nothing on one core.
  bool parallel = true;

  // Throws ValueError unless both deflections are finite and positive.
  void validate() const;
};

struct FaceRange {
  std::uint32_t face_index = 0;      // position in TopExp_Explorer(shape, FACE) order
  std::uint32_t first_triangle = 0;  // triangles of this face are [first, first + count)
  std::uint32_t triangle_count = 0;
};

struct Mesh {
  std::vector<float> vertices;           // 3 per vertex
  std::vector<float> normals;            // 3 per vertex, unit length (zero when undefined)
  std::vector<std::uint32_t> triangles;  // 3 vertex indices per triangle
  std::vector<std::uint32_t> face_ids;   // 1 per triangle
  std::vector<FaceRange> face_ranges;    // one per face, in face order (including unmeshed ones)

  std::size_t vertex_count() const noexcept { return vertices.size() / 3; }
  std::size_t triangle_count() const noexcept { return triangles.size() / 3; }
  bool empty() const noexcept { return triangles.empty(); }
  // Min and max corner; both zero for an empty mesh.
  std::array<std::array<float, 3>, 2> bounds() const noexcept;
};

// Faces for which OCCT produced no triangulation are listed in the ranges with
// a zero triangle count.  Throws ValueError for a null shape or bad parameters
// and KernelError when the mesher itself fails.
Mesh mesh(const TopoDS_Shape& shape, const MeshParameters& parameters = {});
inline Mesh mesh(const Shape& shape, const MeshParameters& parameters = {}) {
  return mesh(shape.wrapped(), parameters);
}

// ---------------------------------------------------------------------------
// Per face (kernel/ocp_mesh.py)
// ---------------------------------------------------------------------------
struct FaceTessellation {
  std::vector<Vec3> vertices;                          // world coordinates
  std::vector<std::array<std::uint32_t, 3>> triangles;  // already wound for the face's orientation
  std::vector<Vec3> node_normals;                      // empty when OCCT computed none

  // One normal triple per triangle: the node normals when there are any
  // (flipped for reversed faces), otherwise the flat triangle normal.
  std::vector<std::array<Vec3, 3>> corner_normals() const;
};

// Meshes `face` on its own (a copy, like mesh()) and returns its triangulation;
// empty when the mesher produced none.  tolerance = linear deflection.
FaceTessellation tessellate_face_with_normals(const TopoDS_Face& face,
                                              double tolerance = kDefaultLinearDeflection,
                                              double angular_tolerance = kDefaultAngularDeflection);

// vertices and triangles only: kernel/ocp_mesh.py tessellate_face.
inline FaceTessellation tessellate_face(const TopoDS_Face& face, double tolerance = kDefaultLinearDeflection,
                                        double angular_tolerance = kDefaultAngularDeflection) {
  FaceTessellation result = tessellate_face_with_normals(face, tolerance, angular_tolerance);
  result.node_normals.clear();
  return result;
}

// ---------------------------------------------------------------------------
// TriMesh (_internal/mesh.py)
// ---------------------------------------------------------------------------
struct FaceTriangleRange {
  std::int64_t face_index = 0;
  std::int64_t start = 0;
  std::int64_t count = 0;
  std::string source_topo_id;  // the face's topo_id in the solid the mesh was built from
};

struct TriMesh {
  std::vector<double> vertices;            // 3 per vertex
  std::vector<std::int64_t> triangles;     // 3 per triangle
  std::vector<double> corner_normals;      // 9 per triangle: three unit normals
  std::vector<FaceTriangleRange> face_triangle_ranges;
  double linear_tolerance = kDefaultLinearDeflection;
  double angular_tolerance = kDefaultAngularDeflection;

  std::size_t vertex_count() const noexcept { return vertices.size() / 3; }
  std::size_t triangle_count() const noexcept { return triangles.size() / 3; }
  // (min, max); both (0, 0, 0) for a mesh without vertices.
  std::array<Vec3, 2> bounds() const noexcept;
};

// Python: _internal.mesh.build_solid_trimesh.  Throws on failure.
TriMesh build_solid_trimesh(const Shape& solid, double linear_tolerance = kDefaultLinearDeflection,
                            double angular_tolerance = kDefaultAngularDeflection);

// Python: _internal.mesh.cached_mesh.  The mesh is built on first use and kept
// per (shape identity, tolerances) in a small process-wide least-recently-used
// cache (it is derived data: never serialized, never copied).  A failure is
// recorded as the runtime value "mesh.error" on the shape and nullptr returned.
std::shared_ptr<const TriMesh> cached_mesh(const Shape& solid,
                                           double linear_tolerance = kDefaultLinearDeflection,
                                           double angular_tolerance = kDefaultAngularDeflection);
// The diagnostic recorded by the last failed cached_mesh on this shape, or "".
std::string mesh_error(const Shape& solid);
// Drop every cached mesh (tests, memory pressure).
void clear_mesh_cache();

// ---------------------------------------------------------------------------
// Welded surface mesh (exporter/_surface_mesh.py): what STL/OBJ/GLB write.
// ---------------------------------------------------------------------------
struct WeldedMesh {
  std::vector<double> vertices;                          // 3 per vertex
  std::vector<std::array<std::int32_t, 3>> triangles;
  std::size_t vertex_count() const noexcept { return vertices.size() / 3; }
};

struct SurfaceMeshParameters {
  double linear_deflection = 0.1;
  double angular_deflection_degrees = 20.0;  // in (0, 180]
  bool relative = false;
};

// Tessellate one solid (or any shape) and weld coincident vertices across faces.
// Collapsed triangles are dropped.  Throws RuntimeError when a face cannot be
// tessellated or nothing is left (the Python exporter's behaviour).
WeldedMesh tessellate_solid(const TopoDS_Shape& solid, const SurfaceMeshParameters& parameters = {});

}  // namespace scad::io
