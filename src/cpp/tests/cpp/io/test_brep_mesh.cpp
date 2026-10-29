// BREP bytes and tessellation.
#include "doctest.h"

#include <cmath>
#include <set>
#include <sstream>
#include <thread>

#include <BRepBuilderAPI_Transform.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>

#include "scad/core/error.hpp"
#include "scad/io/brep.hpp"
#include "scad/io/mesh.hpp"
#include "scad/kernel/properties.hpp"

using namespace scad;
using namespace scad::io;

namespace {

TopoDS_Shape box(double x, double y, double z) {
  return BRepPrimAPI_MakeBox(x, y, z).Solid();
}

// Signed volume of a closed, outward-wound triangle mesh (divergence theorem).
double mesh_volume(const Mesh& m) {
  double volume = 0.0;
  const auto v = [&](std::uint32_t i) {
    return Vec3{static_cast<double>(m.vertices[3 * i]), static_cast<double>(m.vertices[3 * i + 1]),
                static_cast<double>(m.vertices[3 * i + 2])};
  };
  for (std::size_t t = 0; t < m.triangle_count(); ++t)
    volume += v(m.triangles[3 * t]).dot(v(m.triangles[3 * t + 1]).cross(v(m.triangles[3 * t + 2]))) / 6.0;
  return volume;
}

}  // namespace

TEST_CASE("BREP bytes: BinTools V4 round trip keeps the geometry exactly") {
  const TopoDS_Shape original = box(10, 20, 30);
  const Bytes bytes = to_brep_bytes(original);
  CHECK(bytes.rfind("\nOpen CASCADE Topology V4, (c) Open Cascade\n", 0) == 0);
  const TopoDS_Shape back = from_brep_bytes(bytes);
  CHECK(kernel::volume(back) == doctest::Approx(6000.0));
  CHECK(kernel::bounding_box(back).xlen() == doctest::Approx(10.0));
  // A shape is not written with its mesh: the bytes do not depend on meshing it.
  (void)mesh(original);
  CHECK(to_brep_bytes(original) == bytes);
}

TEST_CASE("BREP bytes: ASCII BRep is read, garbage and truncation are rejected") {
  const TopoDS_Shape original = BRepPrimAPI_MakeCylinder(5.0, 10.0).Solid();
  std::ostringstream ascii;
  BRepTools::Write(original, ascii);
  CHECK(kernel::volume(from_brep_bytes(ascii.str())) == doctest::Approx(kernel::volume(original)));

  CHECK_THROWS_AS((void)from_brep_bytes(""), ValueError);
  CHECK_THROWS_AS((void)from_brep_bytes("hello, world"), ValueError);
  CHECK_THROWS_AS((void)to_brep_bytes(TopoDS_Shape()), ValueError);
  const Bytes bytes = to_brep_bytes(original);
  // A truncated BinTools stream must fail with an exception, not return a half shape.
  bool failed = false;
  try {
    const TopoDS_Shape partial = from_brep_bytes(bytes.substr(0, bytes.size() / 2));
    failed = partial.IsNull();
  } catch (const std::exception&) {
    failed = true;
  }
  CHECK(failed);
}

TEST_CASE("BREP bytes: canonical bytes are a fixed point of read and write") {
  const TopoDS_Shape shape = BRepPrimAPI_MakeSphere(7.0).Solid();
  const Bytes canonical = canonical_brep_bytes(shape);
  CHECK(canonical_brep_bytes(from_brep_bytes(canonical)) == canonical);
  CHECK(brep_sha256(shape).rfind("sha256:", 0) == 0);
  CHECK(brep_sha256(shape) == brep_sha256(from_brep_bytes(canonical)));
}

TEST_CASE("BREP handles: to_brep / from_brep keep the kind") {
  const Solid solid(box(1, 2, 3));
  const Shape back = from_brep(to_brep(solid));
  CHECK(back.kind() == Kind::Solid);
  CHECK(Solid(back).volume() == doctest::Approx(6.0));
}

TEST_CASE("mesh(): a box is 12 triangles on 24 unshared vertices, wound outward") {
  const Mesh m = mesh(box(10, 20, 30));
  CHECK(m.triangle_count() == 12);
  CHECK(m.vertex_count() == 24);
  CHECK(m.normals.size() == m.vertices.size());
  CHECK(m.face_ids.size() == 12);
  CHECK(m.face_ranges.size() == 6);
  CHECK(mesh_volume(m) == doctest::Approx(6000.0).epsilon(1e-6));
  std::multiset<std::uint32_t> faces(m.face_ids.begin(), m.face_ids.end());
  for (std::uint32_t f = 0; f < 6; ++f)
    CHECK(faces.count(f) == 2);
  for (std::size_t i = 0; i < m.vertex_count(); ++i) {
    const double n =
        std::sqrt(double(m.normals[3 * i]) * m.normals[3 * i] + double(m.normals[3 * i + 1]) * m.normals[3 * i + 1] +
                  double(m.normals[3 * i + 2]) * m.normals[3 * i + 2]);
    CHECK(n == doctest::Approx(1.0).epsilon(1e-5));
  }
  const auto bounds = m.bounds();
  CHECK(bounds[0][0] == 0.0F);
  CHECK(bounds[1][2] == 30.0F);
}

TEST_CASE("mesh(): per-vertex normals point out of the solid") {
  const TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(5.0).Solid();
  const Mesh m = mesh(sphere);
  for (std::size_t i = 0; i < m.vertex_count(); ++i) {
    const double dot = double(m.vertices[3 * i]) * m.normals[3 * i] +
                       double(m.vertices[3 * i + 1]) * m.normals[3 * i + 1] +
                       double(m.vertices[3 * i + 2]) * m.normals[3 * i + 2];
    CHECK(dot > 0.0);  // the sphere is centred at the origin: outward normals have a positive dot with the position
  }
  CHECK(mesh_volume(m) == doctest::Approx(4.0 / 3.0 * kPi * 125.0).epsilon(0.02));
}

TEST_CASE("mesh(): deflection controls density, location is honoured, input stays untouched") {
  const TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(5.0, 10.0).Solid();
  MeshParameters coarse;
  coarse.linear_deflection = 1.0;
  coarse.angular_deflection = 0.8;
  MeshParameters fine;
  fine.linear_deflection = 0.01;
  fine.angular_deflection = 0.1;
  CHECK(mesh(cylinder, fine).triangle_count() > 4 * mesh(cylinder, coarse).triangle_count());
  CHECK(mesh_volume(mesh(cylinder, fine)) == doctest::Approx(kPi * 25 * 10).epsilon(2e-3));

  gp_Trsf move;
  move.SetTranslation(gp_Vec(100, 0, 0));
  const TopoDS_Shape moved = cylinder.Moved(TopLoc_Location(move));
  const auto bounds = mesh(moved).bounds();
  CHECK(bounds[0][0] == doctest::Approx(95.0F));
  CHECK(bounds[1][0] == doctest::Approx(105.0F));

  for (TopExp_Explorer faces(cylinder, TopAbs_FACE); faces.More(); faces.Next()) {
    TopLoc_Location location;
    CHECK(BRep_Tool::Triangulation(TopoDS::Face(faces.Current()), location).IsNull());
  }
}

TEST_CASE("mesh(): parameters are validated and parallel equals serial") {
  MeshParameters bad;
  bad.linear_deflection = 0.0;
  CHECK_THROWS_AS((void)mesh(box(1, 1, 1), bad), ValueError);
  bad.linear_deflection = std::nan("");
  CHECK_THROWS_AS((void)mesh(box(1, 1, 1), bad), ValueError);
  CHECK_THROWS_AS((void)mesh(TopoDS_Shape()), ValueError);

  const TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(5.0).Solid();
  MeshParameters serial;
  serial.parallel = false;
  MeshParameters parallel;
  parallel.parallel = true;
  CHECK(mesh(sphere, serial).triangle_count() == mesh(sphere, parallel).triangle_count());
}

TEST_CASE("mesh(): the same shape meshed from several threads gives the same mesh") {
  const TopoDS_Shape sphere = BRepPrimAPI_MakeSphere(5.0).Solid();
  const std::size_t expected = mesh(sphere).triangle_count();
  std::vector<std::size_t> counts(6, 0);
  std::vector<std::thread> threads;
  for (std::size_t i = 0; i < counts.size(); ++i)
    threads.emplace_back([&, i] { counts[i] = mesh(sphere).triangle_count(); });
  for (auto& t : threads)
    t.join();
  for (const std::size_t c : counts)
    CHECK(c == expected);
}

TEST_CASE("tessellate_face_with_normals: per-corner normals follow the face orientation") {
  const TopoDS_Shape solid = box(2, 2, 2);
  int up = 0, down = 0;
  for (TopExp_Explorer faces(solid, TopAbs_FACE); faces.More(); faces.Next()) {
    const FaceTessellation t = tessellate_face_with_normals(TopoDS::Face(faces.Current()));
    CHECK(t.triangles.size() == 2);
    for (const auto& corners : t.corner_normals())
      for (const Vec3& n : corners) {
        CHECK(n.norm() == doctest::Approx(1.0).epsilon(1e-5));
        if (n.z > 0.99)
          ++up;
        if (n.z < -0.99)
          ++down;
      }
    // The winding and the normals agree on the outward side.
    const auto& tri = t.triangles.front();
    const Vec3 flat =
        (t.vertices[tri[1]] - t.vertices[tri[0]]).cross(t.vertices[tri[2]] - t.vertices[tri[0]]).normalized();
    CHECK(flat.dot(t.corner_normals().front()[0]) > 0.99);
  }
  CHECK(up == 6);
  CHECK(down == 6);
}

TEST_CASE("build_solid_trimesh and cached_mesh") {
  clear_mesh_cache();
  const Solid solid(box(10, 20, 30));
  const TriMesh m = build_solid_trimesh(solid);
  CHECK(m.triangle_count() == 12);
  CHECK(m.face_triangle_ranges.size() == 6);
  std::int64_t sum = 0;
  for (std::size_t i = 0; i < m.face_triangle_ranges.size(); ++i) {
    CHECK(m.face_triangle_ranges[i].face_index == static_cast<std::int64_t>(i));
    CHECK_FALSE(m.face_triangle_ranges[i].source_topo_id.empty());
    sum += m.face_triangle_ranges[i].count;
  }
  CHECK(sum == 12);
  CHECK(m.corner_normals.size() == 12 * 9);
  CHECK(m.bounds()[0].x == 0.0);
  CHECK(m.bounds()[1].z == 30.0);

  const auto first = cached_mesh(solid);
  REQUIRE(first != nullptr);
  CHECK(cached_mesh(solid) == first);            // cache hit
  CHECK(cached_mesh(solid, 0.1, 0.1) != first);  // different tolerance
  CHECK(mesh_error(solid).empty());
  gp_Trsf move;
  move.SetTranslation(gp_Vec(1, 2, 3));
  const Solid moved(solid.wrapped().Moved(TopLoc_Location(move)));
  const auto mesh_of_moved = cached_mesh(moved);
  REQUIRE(mesh_of_moved != nullptr);
  CHECK(mesh_of_moved->bounds()[0].x == doctest::Approx(1.0));
  CHECK(mesh_of_moved->bounds()[1].z == doctest::Approx(33.0));

  CHECK(cached_mesh(solid, -1.0) == nullptr);
  CHECK_FALSE(mesh_error(solid).empty());
}

TEST_CASE("tessellate_solid welds vertices across faces") {
  const WeldedMesh m = tessellate_solid(box(10, 20, 30));
  CHECK(m.vertex_count() == 8);
  CHECK(m.triangles.size() == 12);
  SurfaceMeshParameters bad;
  bad.angular_deflection_degrees = 181.0;
  CHECK_THROWS_AS((void)tessellate_solid(box(1, 1, 1), bad), ValueError);
  bad = {};
  bad.linear_deflection = 0.0;
  CHECK_THROWS_AS((void)tessellate_solid(box(1, 1, 1), bad), ValueError);
}
