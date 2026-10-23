// load_brep_region_rsolid / load_brep_region_rshell on snapshots this library writes.
#include "support.hpp"

#include <filesystem>

#include <BRepPrimAPI_MakeBox.hxx>

#include "scad/io/brep_region.hpp"
#include "scad/io/files.hpp"
#include "scad/io/hash.hpp"
#include "scad/kernel/builders.hpp"

using namespace scad;
using namespace scad::geometry_test;
namespace fs = std::filesystem;

namespace {

struct Sidecar {
  fs::path directory = fs::temp_directory_path() / "scad_geometry_region";
  fs::path file;
  std::string sha256;

  explicit Sidecar(io::RegionRootKind kind) {
    fs::remove_all(directory);
    fs::create_directories(directory);
    const TopoDS_Solid solid = kernel::make_box_solid({0, 0, 0}, 10, 20, 30);
    std::vector<std::string> face_ids;
    TopoDS_Shape shape = solid;
    if (kind == io::RegionRootKind::Shell) {
      face_ids = {"face:0", "face:1", "face:2", "face:3", "face:4", "face:5"};
      shape = io::require_single_valid_shell(solid);
    }
    const io::Bytes bytes = io::make_region_artifact(shape, kind, {.name = "box.step", .byte_length = 1, .content_hash = "sha256:" + std::string(64, 'a')}, face_ids);
    file = directory / "region.scadbrep";
    io::write_file(file, bytes);
    sha256 = io::sha256_tagged(bytes);
  }
  ~Sidecar() {
    std::error_code ignored;
    fs::remove_all(directory, ignored);
  }
  std::string path() const { return io::path_to_utf8(file); }
};

}  // namespace

TEST_CASE("load_brep_region_rsolid decodes, tags and attributes the snapshot") {
  const Sidecar sidecar(io::RegionRootKind::Solid);
  const Solid solid = load_brep_region_rsolid(sidecar.path(), sidecar.sha256, "part");
  CHECK(solid.volume() == doctest::Approx(6000.0));
  CHECK(has_tag(solid, "imported"));
  CHECK(has_tag(solid, "sidecar"));
  CHECK(has_tag(solid, "solid"));
  CHECK(has_tag(solid, "part.solid"));
  CHECK(has_tag(solid, "provenance.exact_transcription"));
  CHECK(solid.get_metadata("brep_region").find("artifact_sha256")->as_string() == sidecar.sha256);

  const std::vector<Face> faces = solid.faces();
  REQUIRE(faces.size() == 6);
  for (const Face& face : faces) {
    CHECK(has_tag(face, "provenance.exact_transcription"));
    CHECK(face.get_metadata("provenance").find("construction")->as_string() == "exact_transcription");
  }
  // The same snapshot gives the same binding ids: they are derived from the digest.
  const Solid again = load_brep_region_rsolid(sidecar.path(), sidecar.sha256);
  CHECK(again.local_bindings().back().binding_id == solid.local_bindings().back().binding_id);
}

TEST_CASE("load_brep_region_rshell loads a face region") {
  const Sidecar sidecar(io::RegionRootKind::Shell);
  const Shell shell = load_brep_region_rshell(sidecar.path(), sidecar.sha256);
  CHECK(shell.area() == doctest::Approx(2 * (200 + 300 + 600)));
  CHECK(has_tag(shell, "shell"));
  CHECK(shell.faces().front().get_metadata("provenance").find("source_face_id")->as_string() == "face:0");
}

TEST_CASE("snapshot failures are reported by the operator that was asked") {
  const Sidecar sidecar(io::RegionRootKind::Solid);
  const auto wrong_hash = failure_of([&] { load_brep_region_rsolid(sidecar.path(), "sha256:" + std::string(64, '0')); });
  REQUIRE(wrong_hash);
  CHECK(wrong_hash->operation() == "brep_region");  // the io layer's own error passes through

  const auto not_a_shell = failure_of([&] { load_brep_region_rshell(sidecar.path(), sidecar.sha256); });
  REQUIRE(not_a_shell);

  const auto bad_extension = failure_of([&] { load_brep_region_rsolid("region.step", sidecar.sha256); });
  REQUIRE(bad_extension);
  CHECK(bad_extension->operation() == "load_brep_region_rsolid");
  CHECK(bad_extension->guidance().technical_details == "ValueError: path must end in .scadbrep");
}

TEST_CASE("while recording, the locator must be relative") {
  const Sidecar sidecar(io::RegionRootKind::Solid);
  Recording recording;
  const auto absolute = failure_of([&] { load_brep_region_rsolid(sidecar.path(), sidecar.sha256); });
  REQUIRE(absolute);
  CHECK(absolute->guidance().technical_details.find("GraphSession requires a relative .scadbrep path") != std::string::npos);
}
