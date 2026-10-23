// The .scadbrep container, against artifacts written by the Python SDK.
#include "doctest.h"

#include <filesystem>
#include <functional>

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>

#include "scad/core/error.hpp"
#include "scad/io/brep_region.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"
#include "scad/kernel/properties.hpp"

using namespace scad;
using namespace scad::io;
namespace fs = std::filesystem;

namespace {

std::string base64_decode(const std::string& text) {
  static const std::string alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string out;
  unsigned buffer = 0;
  int bits = 0;
  for (const char c : text) {
    if (c == '=') break;
    buffer = (buffer << 6) | static_cast<unsigned>(alphabet.find(c));
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push_back(static_cast<char>((buffer >> bits) & 0xFF));
    }
  }
  return out;
}

// tests/golden/io_scadbrep_reference.json: artifacts written by the Python SDK on OCP 7.9.3.1.
const Value& reference() {
  static const Value value = [] {
    const fs::path file = fs::path(__FILE__).parent_path() / ".." / ".." / "golden" / "io_scadbrep_reference.json";
    return parse_json(read_file(file));
  }();
  return value;
}

Bytes artifact(const char* name) { return base64_decode(reference().find(name)->find("artifact_b64")->as_string()); }

struct TempDir {
  fs::path path = fs::temp_directory_path() / "scad_io_region";
  TempDir() {
    fs::remove_all(path);
    fs::create_directories(path);
  }
  ~TempDir() {
    std::error_code ignored;
    fs::remove_all(path, ignored);
  }
};

// Rewrites the manifest of an artifact and keeps the container consistent.
Bytes with_manifest(const Bytes& original, const std::function<void(Value&)>& edit) {
  std::uint64_t manifest_size = 0;
  for (int i = 0; i < 8; ++i) manifest_size = (manifest_size << 8) | static_cast<unsigned char>(original[16 + static_cast<std::size_t>(i)]);
  Value manifest = parse_json(original.substr(32, static_cast<std::size_t>(manifest_size)));
  const std::string payload = original.substr(32 + static_cast<std::size_t>(manifest_size));
  edit(manifest);
  return encode_artifact(manifest, payload);
}

}  // namespace

TEST_CASE("brep_region: artifacts written by the Python SDK decode (box, cylinder, one-face shell)") {
  for (const char* name : {"box", "cylinder"}) {
    CAPTURE(name);
    const DecodedRegion region = decode_artifact(artifact(name), RegionRootKind::Solid);
    CHECK(region.root_kind == RegionRootKind::Solid);
    CHECK(region.shape.ShapeType() == TopAbs_SOLID);
    CHECK(kernel::volume(region.shape) == doctest::Approx(reference().find(name)->find("volume")->as_double()).epsilon(1e-9));
    CHECK(region.manifest.find("profile")->as_string().rfind("scadbrep-1-ocp-7.9.3.1-", 0) == 0);
  }
  const DecodedRegion top = decode_artifact(artifact("box_top"), RegionRootKind::Shell);
  CHECK(top.shape.ShapeType() == TopAbs_SHELL);
  CHECK(top.manifest.find("region")->find("kind")->as_string() == "face_shell");
  CHECK_THROWS_AS((void)decode_artifact(artifact("box_top"), RegionRootKind::Solid), Error);
  CHECK(canonical_json(top.manifest) == canonical_json(*reference().find("box_top")->find("manifest")));
}

TEST_CASE("brep_region: our writer's manifest has the Python manifest's shape") {
  const Value& python_manifest = *reference().find("box")->find("manifest");
  const DecodedRegion python = decode_artifact(artifact("box"));
  const Value& recorded = *python_manifest.find("source");
  RegionSource source;
  source.name = recorded.find("name")->as_string();
  source.byte_length = static_cast<std::size_t>(recorded.find("byte_length")->as_int());
  source.content_hash = recorded.find("content_hash")->as_string();
  source.transferred_root_count = static_cast<int>(recorded.find("transferred_root_count")->as_int());
  const Bytes ours = make_region_artifact(python.shape, RegionRootKind::Solid, source, {}, "7.9.3.1");
  const DecodedRegion again = decode_artifact(ours);
  // Same document modulo the payload bytes: re-encoding the same shape is deterministic.
  CHECK(canonical_json(again.manifest) == canonical_json(python_manifest));
  CHECK(ours == artifact("box"));
}

TEST_CASE("brep_region: writing and reading our own snapshots") {
  const TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(3.0, 8.0).Solid();
  RegionSource source;
  source.name = "c.step";
  source.byte_length = 10;
  source.content_hash = sha256_tagged("0123456789");
  const Bytes mine = make_region_artifact(cylinder, RegionRootKind::Solid, source);
  const DecodedRegion back = decode_artifact(mine, RegionRootKind::Solid);
  CHECK(kernel::volume(back.shape) == doctest::Approx(kernel::volume(cylinder)));
  CHECK(back.manifest.find("generator")->find("ocp_version")->as_string() == default_ocp_version());
  CHECK(back.manifest.find("region")->find("source_face_ids")->size() == 3);

  // A shell needs its face ids; a solid must not be given any.
  CHECK_THROWS_AS((void)make_region_artifact(cylinder, RegionRootKind::Solid, source, {"face:0"}), ValueError);
  CHECK_THROWS_AS((void)make_region_artifact(BRepPrimAPI_MakeBox(1, 1, 1).Solid(), RegionRootKind::Shell, source), ValueError);
}

TEST_CASE("brep_region: tampering is rejected with a brep_region error") {
  const Bytes good = artifact("box");
  CHECK_NOTHROW((void)decode_artifact(good));
  const auto rejects = [&](const Bytes& data, const char* why) {
    CAPTURE(why);
    try {
      (void)decode_artifact(data);
      FAIL("accepted a damaged artifact");
    } catch (const Error& e) {
      CHECK(e.operation() == "brep_region");
    }
  };
  rejects(good.substr(0, 20), "truncated header");
  rejects(good.substr(0, good.size() - 1), "truncated payload");
  rejects(good + "x", "trailing byte");
  Bytes bad_magic = good;
  bad_magic[0] = 'X';
  rejects(bad_magic, "magic");
  Bytes bad_flags = good;
  bad_flags[15] = 1;
  rejects(bad_flags, "flags");
  Bytes bad_minor = good;
  bad_minor[11] = 1;
  rejects(bad_minor, "minor version");
  Bytes bad_payload = good;
  bad_payload[good.size() - 3] = static_cast<char>(bad_payload[good.size() - 3] ^ 0xFF);
  rejects(bad_payload, "payload bit flip");

  rejects(with_manifest(good, [](Value& m) { m.set("extra", 1); }), "unknown manifest key");
  rejects(with_manifest(good, [](Value& m) { m.erase("provenance"); }), "missing key");
  rejects(with_manifest(good, [](Value& m) { m.set("profile", "scadbrep-1-ocp-7.8.0-bintools-v4-no-mesh"); }),
          "other OCCT minor");
  rejects(with_manifest(good, [](Value& m) { m.find("shape")->set("volume", 5000.0); }), "descriptor drift");
  rejects(with_manifest(good, [](Value& m) { m.find("shape")->set("face_count", 7); }), "count drift");
  rejects(with_manifest(good, [](Value& m) { m.find("shape")->find("face_fingerprints")->as_array()[0].set("area", 1.0); }),
          "face geometry drift");
  rejects(with_manifest(good, [](Value& m) { m.find("provenance")->set("construction", "approximate"); }), "provenance");
  rejects(with_manifest(good, [](Value& m) { m.find("coordinate_system")->set("length_unit", "m"); }), "unit");
  rejects(with_manifest(good, [](Value& m) { m.find("source")->set("content_hash", "sha256:xyz"); }), "source hash");

  // A manifest that is valid JSON but not RFC 8785 canonical (spaces) is refused.
  std::uint64_t manifest_size = 0;
  for (int i = 0; i < 8; ++i) manifest_size = (manifest_size << 8) | static_cast<unsigned char>(good[16 + static_cast<std::size_t>(i)]);
  const std::string manifest = good.substr(32, static_cast<std::size_t>(manifest_size));
  const std::string reformatted = python_json_dumps(parse_json(manifest), true, true);
  Bytes rebuilt = good.substr(0, 16);
  for (int shift = 56; shift >= 0; shift -= 8) rebuilt.push_back(static_cast<char>((reformatted.size() >> shift) & 0xFF));
  rebuilt += good.substr(24, 8) + reformatted + good.substr(32 + static_cast<std::size_t>(manifest_size));
  rejects(rebuilt, "non-canonical JSON");
}

TEST_CASE("brep_region: read_artifact checks the digest and confines replay to its root") {
  const TempDir dir;
  const Bytes data = artifact("box");
  const std::string digest = sha256_tagged(data);
  fs::create_directories(dir.path / "sub");
  write_file(dir.path / "sub" / "body.scadbrep", data);

  const RegionFile file = read_artifact(dir.path / "sub" / "body.scadbrep", digest, RegionRootKind::Solid);
  CHECK(file.sha256 == digest);
  CHECK(file.shape.ShapeType() == TopAbs_SOLID);
  // The digest may omit the prefix and use any case.
  CHECK_NOTHROW((void)read_artifact(dir.path / "sub" / "body.scadbrep", digest.substr(7), RegionRootKind::Solid));
  std::string upper = digest;
  for (char& c : upper) c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
  CHECK_NOTHROW((void)read_artifact(dir.path / "sub" / "body.scadbrep", " " + upper + " ", RegionRootKind::Solid));

  CHECK_THROWS_WITH_AS((void)read_artifact(dir.path / "sub" / "body.scadbrep", sha256_tagged("other"), RegionRootKind::Solid),
                       doctest::Contains("SHA-256"), Error);
  CHECK_THROWS_AS((void)read_artifact(dir.path / "missing.scadbrep", digest, RegionRootKind::Solid), Error);

  const std::optional<fs::path> root = dir.path;
  CHECK_NOTHROW((void)read_artifact("sub/body.scadbrep", digest, RegionRootKind::Solid, root));
  CHECK_THROWS_WITH_AS((void)read_artifact("../elsewhere.scadbrep", digest, RegionRootKind::Solid, root),
                       doctest::Contains("escapes"), Error);
}

#ifndef _WIN32
TEST_CASE("brep_region: replay refuses a path through a symbolic link") {
  const TempDir dir;
  const Bytes data = artifact("box");
  fs::create_directories(dir.path / "sub");
  write_file(dir.path / "sub" / "body.scadbrep", data);
  fs::create_directory_symlink(dir.path / "sub", dir.path / "link");
  const std::optional<fs::path> root = dir.path;
  CHECK_THROWS_WITH_AS((void)read_artifact("link/body.scadbrep", sha256_tagged(data), RegionRootKind::Solid, root),
                       doctest::Contains("symbolic links"), Error);
}
#endif

TEST_CASE("brep_region: copy_step_solid_region reproduces copy_step_region_rpath") {
  const TempDir dir;
  export_step_shapes({BRepPrimAPI_MakeBox(10, 20, 30).Solid()}, dir.path / "target.step");
  const fs::path out = copy_step_solid_region(dir.path / "target.step", dir.path / "target.scadbrep", "7.9.3.1");
  const Bytes data = read_file(out);
  const RegionFile file = read_artifact(out, sha256_tagged(data), RegionRootKind::Solid);
  CHECK(kernel::volume(file.shape) == doctest::Approx(6000.0));
  CHECK(file.manifest.find("source")->find("name")->as_string() == "target.step");
  CHECK(file.manifest.find("source")->find("content_hash")->as_string() == sha256_tagged(read_file(dir.path / "target.step")));
  CHECK_THROWS_AS((void)copy_step_solid_region(dir.path / "target.step", dir.path / "target.txt"), ValueError);
  CHECK_THROWS_AS((void)copy_step_solid_region(dir.path / "target.step", dir.path / "no_dir" / "x.scadbrep"), ValueError);
  CHECK_THROWS_AS((void)copy_step_solid_region(dir.path / "absent.step", dir.path / "x.scadbrep"), ValueError);
}

TEST_CASE("brep_region: locator checks (_brep_region_path)") {
  CHECK(checked_region_path("models/body.scadbrep", true) == "models/body.scadbrep");
  CHECK(checked_region_path("./models//body.scadbrep", true) == "models/body.scadbrep");
  CHECK(checked_region_path("body.SCADBREP", false) == "body.SCADBREP");
  CHECK_THROWS_AS((void)checked_region_path("body:hidden.scadbrep", true), ValueError);
  CHECK_THROWS_AS((void)checked_region_path("/abs/body.scadbrep", true), ValueError);
  CHECK_THROWS_AS((void)checked_region_path("../body.scadbrep", true), ValueError);
  CHECK_THROWS_AS((void)checked_region_path("a\\b.scadbrep", true), ValueError);
  CHECK_THROWS_AS((void)checked_region_path("body.step", false), ValueError);
  CHECK_NOTHROW((void)checked_region_path("/abs/body.scadbrep", false));
}
