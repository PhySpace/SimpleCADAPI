// File exchange: STEP, STL, OBJ, GLB, BREP.
#include "doctest.h"

#include <cmath>
#include <cstring>
#include <filesystem>
#include <string>

#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>
#include <BRepBuilderAPI_Transform.hxx>

#include "scad/core/error.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/json.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;
using namespace scad::io;
namespace fs = std::filesystem;

namespace {

struct TempDir {
  fs::path path;
  TempDir() {
    path = fs::temp_directory_path() / path_from_utf8("scad_io_exchange_\xC3\xA9_\xE6\xA8\xA1\xE5\x9E\x8B");
    fs::remove_all(path);
    fs::create_directories(path);
  }
  ~TempDir() {
    std::error_code ignored;
    fs::remove_all(path, ignored);
  }
};

TopoDS_Shape box(double x, double y, double z) {
  return BRepPrimAPI_MakeBox(x, y, z).Solid();
}

TopoDS_Shape moved(const TopoDS_Shape& s, double dx) {
  gp_Trsf t;
  t.SetTranslation(gp_Vec(dx, 0, 0));
  return BRepBuilderAPI_Transform(s, t, true).Shape();
}

std::uint32_t le32(const std::string& s, std::size_t at) {
  std::uint32_t v = 0;
  std::memcpy(&v, s.data() + at, 4);  // test hosts are little-endian
  return v;
}

}  // namespace

TEST_CASE("compounds: lone shapes pass through, empty and null are rejected") {
  const TopoDS_Shape b = box(1, 1, 1);
  CHECK(make_compound({b}).IsSame(b));
  CHECK(make_compound_always({b}).ShapeType() == TopAbs_COMPOUND);
  CHECK(make_compound({b, b}).ShapeType() == TopAbs_COMPOUND);
  CHECK_THROWS_AS((void)make_compound({}), ValueError);
  CHECK_THROWS_AS((void)make_compound_always({}), ValueError);
  CHECK_THROWS_AS((void)make_compound({b, TopoDS_Shape()}), ValueError);
}

TEST_CASE("STEP: write and read back volume, face count and bounding box (Unicode path)") {
  const TempDir dir;
  const TopoDS_Shape fused = BRepAlgoAPI_Fuse(box(10, 20, 30), BRepPrimAPI_MakeCylinder(4.0, 50.0).Shape()).Shape();
  const fs::path file = dir.path / path_from_utf8("\xE9\x9B\xB6\xE4\xBB\xB6.step");
  export_step_shapes({fused}, file);
  REQUIRE(fs::exists(file));
  CHECK(fs::file_size(file) > 1000);

  const StepReadResult back = read_step(file);
  CHECK(back.transferred_roots == 1);
  CHECK(kernel::volume(back.shape) == doctest::Approx(kernel::volume(fused)).epsilon(1e-6));
  CHECK(kernel::faces_of(back.shape).size() == kernel::faces_of(fused).size());
  const auto a = kernel::bounding_box(back.shape), b = kernel::bounding_box(fused);
  CHECK(a.xlen() == doctest::Approx(b.xlen()).epsilon(1e-6));
  CHECK(a.zlen() == doctest::Approx(b.zlen()).epsilon(1e-6));

  const Shape imported = import_step(file);
  CHECK(imported.kind() == Kind::Solid);
}

TEST_CASE("STEP: several shapes go out as one compound, bytes and file agree") {
  const TempDir dir;
  const std::vector<TopoDS_Shape> shapes{box(1, 2, 3), moved(box(4, 5, 6), 10)};
  const Bytes bytes = step_bytes(shapes);
  CHECK(bytes.find("ISO-10303-21") != std::string::npos);
  const StepReadResult from_bytes = read_step_bytes(bytes);
  CHECK(kernel::volume(from_bytes.shape) == doctest::Approx(6.0 + 120.0));
  CHECK(kernel::solids_of(from_bytes.shape).size() == 2);
  export_step_shapes(shapes, dir.path / "two.step");
  // The translator numbers its products from a process-wide counter and stamps the header,
  // so two writes differ in a few bytes; they must still describe the same model.
  const Bytes on_disk = read_file(dir.path / "two.step");
  CHECK(on_disk.size() == bytes.size());
  CHECK(kernel::volume(read_step(dir.path / "two.step").shape) == doctest::Approx(126.0));
}

TEST_CASE("STEP: failures are scad::Error with the operation name") {
  const TempDir dir;
  try {
    (void)read_step(dir.path / "missing.step");
    FAIL("expected an error");
  } catch (const Error& e) {
    CHECK(e.operation() == "import_step");
  }
  write_file(dir.path / "junk.step", "this is not a STEP file");
  CHECK_THROWS_AS((void)read_step(dir.path / "junk.step"), Error);
  CHECK_THROWS_AS(export_step_shapes({}, dir.path / "x.step"), Error);
  CHECK_THROWS_AS(export_step_shapes({box(1, 1, 1)}, dir.path / "nodir" / "x.step"), Error);
  const Bytes bytes = step_bytes({box(1, 1, 1), box(2, 2, 2)});
  StepReadOptions strict;
  strict.require_single_root = true;
  CHECK(read_step_bytes(bytes, "m.step", strict).shape_count == 1);  // a compound is one root
}

TEST_CASE("STL: binary export, read back, triangle counts") {
  const TempDir dir;
  const fs::path file = dir.path / "cube.stl";
  const SurfaceExportReport report = export_stl({box(10, 10, 10)}, file);
  CHECK(report.solid_count == 1);
  CHECK(report.vertex_count == 8);
  CHECK(report.triangle_count == 12);
  const Bytes bytes = read_file(file);
  CHECK(bytes.size() == 84 + 50 * 12);
  CHECK(le32(bytes, 80) == 12);
  CHECK(bytes.substr(0, 39) == "SimpleCAD OpenCASCADE BREP tessellation");

  const Mesh m = read_stl(file);
  CHECK(m.vertex_count() == 8);
  CHECK(m.triangle_count() == 12);
  const auto bounds = m.bounds();
  CHECK(bounds[1][0] == 10.0F);

  // Two solids are welded separately and concatenated.
  const SurfaceExportReport two = export_stl({box(1, 1, 1), moved(box(1, 1, 1), 5)}, dir.path / "two.stl");
  CHECK(two.solid_count == 2);
  CHECK(two.triangle_count == 24);
  CHECK(two.vertex_count == 16);
  // A compound of solids counts every solid.
  CHECK(export_stl({make_compound({box(1, 1, 1), moved(box(1, 1, 1), 5)})}, dir.path / "c.stl").solid_count == 2);
}

TEST_CASE("STL: export_stl_shape writes ASCII facets, one per mesh triangle") {
  const TempDir dir;
  const fs::path file = dir.path / "a.stl";
  export_stl_shape(box(2, 3, 4), file);
  const Bytes text = read_file(file);
  CHECK(text.rfind("solid ", 0) == 0);
  std::size_t facets = 0;
  for (std::size_t at = text.find("facet normal"); at != std::string::npos; at = text.find("facet normal", at + 1))
    ++facets;
  CHECK(facets == 12);
  const Mesh m = read_stl(file);
  CHECK(m.triangle_count() == 12);
  CHECK(m.vertex_count() == 8);

  const TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape();
  export_stl_shape(cylinder, dir.path / "cyl.stl");
  const Mesh round = read_stl(dir.path / "cyl.stl");
  CHECK(round.triangle_count() > 20);
  CHECK(round.bounds()[1][2] == doctest::Approx(10.0F));
  CHECK_THROWS_AS(export_stl_shape(TopoDS_Shape(), dir.path / "n.stl"), Error);
}

TEST_CASE("STL: reader rejects junk, handles ASCII without a header word") {
  CHECK_THROWS_AS((void)read_stl_bytes("definitely not stl"), Error);
  CHECK_THROWS_AS((void)read_stl_bytes(""), Error);
  const std::string ascii =
      "solid t\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n"
      " endfacet\nendsolid t\n";
  const Mesh m = read_stl_bytes(ascii);
  CHECK(m.triangle_count() == 1);
  CHECK(m.normals[2] == doctest::Approx(1.0F));
  CHECK_THROWS_AS((void)read_stl_bytes("solid t\n facet normal 0 0 1\n outer loop\n vertex 0 0 0\n vertex 1 0 x\n"),
                  Error);
}

TEST_CASE("STL: a mesh sews back into a closed solid") {
  const TempDir dir;
  export_stl({box(10, 20, 30)}, dir.path / "b.stl");
  const Shape solid = import_stl_shape(dir.path / "b.stl");
  REQUIRE(solid.kind() == Kind::Solid);
  CHECK(Solid(solid).volume() == doctest::Approx(6000.0).epsilon(1e-6));
  CHECK(Solid(solid).faces().size() == 12);
}

TEST_CASE("OBJ: v and f records with 17 significant digits") {
  const TempDir dir;
  const SurfaceExportReport report = export_obj({box(1.5, 2, 3)}, dir.path / "b.obj");
  CHECK(report.triangle_count == 12);
  const Bytes text = read_file(dir.path / "b.obj");
  CHECK(text.rfind("# SimpleCAD OpenCASCADE BREP tessellation\n", 0) == 0);
  CHECK(text.find("\r") == std::string::npos);
  std::size_t v = 0, f = 0;
  for (std::size_t at = 0; at < text.size();) {
    const std::size_t end = text.find('\n', at);
    if (text.compare(at, 2, "v ") == 0)
      ++v;
    if (text.compare(at, 2, "f ") == 0)
      ++f;
    at = end + 1;
  }
  CHECK(v == 8);
  CHECK(f == 12);
  CHECK(text.find("v 1.5 2 3\n") != std::string::npos);
}

TEST_CASE("GLB: a valid glTF 2.0 binary container") {
  const TempDir dir;
  export_glb({box(10, 20, 30)}, dir.path / "b.glb");
  const Bytes glb = read_file(dir.path / "b.glb");
  REQUIRE(glb.size() > 28);
  CHECK(le32(glb, 0) == 0x46546C67U);
  CHECK(le32(glb, 4) == 2);
  CHECK(le32(glb, 8) == glb.size());
  const std::uint32_t json_length = le32(glb, 12);
  CHECK(le32(glb, 16) == 0x4E4F534AU);
  CHECK(json_length % 4 == 0);
  const Value json = parse_json(glb.substr(20, json_length));
  CHECK(json.find("asset")->find("version")->as_string() == "2.0");
  const auto& accessors = json.find("accessors")->as_array();
  REQUIRE(accessors.size() == 3);
  CHECK(accessors[0].find("count")->as_int() == 36);
  CHECK(accessors[1].find("count")->as_int() == 24);
  CHECK(accessors[1].find("max")->as_array()[2].as_double() == 30.0);
  const std::size_t bin_at = 20 + json_length;
  CHECK(le32(glb, bin_at + 4) == 0x004E4942U);
  CHECK(le32(glb, bin_at) == static_cast<std::uint32_t>(36 * 4 + 24 * 12 * 2));
  CHECK(glb.size() == bin_at + 8 + le32(glb, bin_at));
  CHECK_THROWS_AS(export_glb({}, dir.path / "e.glb"), Error);
}

TEST_CASE("BREP files: round trip through export_brep / import_brep") {
  const TempDir dir;
  const Solid solid(box(3, 4, 5));
  export_brep(solid, dir.path / "s.brep");
  const Shape back = import_brep(dir.path / "s.brep");
  CHECK(back.kind() == Kind::Solid);
  CHECK(Solid(back).volume() == doctest::Approx(60.0));
  CHECK_THROWS_AS((void)import_brep(dir.path / "absent.brep"), Error);
  write_file(dir.path / "bad.brep", "garbage garbage garbage");
  CHECK_THROWS_AS((void)import_brep(dir.path / "bad.brep"), Error);
}
