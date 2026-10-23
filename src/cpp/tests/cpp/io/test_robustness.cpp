// Hostile and damaged input must end in an exception, never in a crash or a hang.
// (Run under ASan/UBSan: -DSCAD_SANITIZE=ON.)  The BREP section itself is OCCT's parser and is
// guarded by the container checksum, so these tests damage the parts this library parses.
#include "doctest.h"

#include <random>

#include <BRepPrimAPI_MakeBox.hxx>

#include "scad/core/error.hpp"
#include "scad/io/brep_region.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"
#include "scad/io/serialize.hpp"
#include "scad/topo/shape.hpp"

using namespace scad;
using namespace scad::io;

namespace {

// Flips a few bytes of `text` in [begin, end).
std::string mutate(std::string text, std::size_t begin, std::size_t end, std::mt19937& rng) {
  std::uniform_int_distribution<std::size_t> position(begin, end - 1);
  std::uniform_int_distribution<int> value(0, 255);
  const int edits = 1 + static_cast<int>(rng() % 4);
  for (int i = 0; i < edits; ++i) text[position(rng)] = static_cast<char>(value(rng));
  if (rng() % 5 == 0) text.erase(position(rng) % (text.size() - begin) + begin, 1 + rng() % 3);
  return text;
}

std::string with_checksum(std::string frame) {
  const std::uint32_t crc = crc32(std::string_view(frame).substr(40));
  for (int i = 0; i < 4; ++i) frame[32 + static_cast<std::size_t>(i)] = static_cast<char>((crc >> (24 - 8 * i)) & 0xFF);
  return frame;
}

}  // namespace

TEST_CASE("fuzz: parse_json never crashes") {
  std::mt19937 rng(7);
  const std::string seed = R"({"a":[1,2.5e-3,true,null,"xé😀"],"b":{"c":-12,"d":[[],{}]},"e":"s"})";
  int parsed = 0;
  for (int i = 0; i < 2000; ++i) {
    const std::string text = mutate(seed, 0, seed.size(), rng);
    try {
      (void)parse_json(text);
      ++parsed;
    } catch (const ValueError&) {
    }
  }
  CHECK(parsed < 2000);
}

TEST_CASE("fuzz: a damaged state section never crashes deserialize") {
  Solid solid(BRepPrimAPI_MakeBox(1, 2, 3).Solid());
  solid.add_tag("role.a");
  solid.faces()[1].add_tag("role.b");
  solid.set_metadata("m", Value::object());
  const Bytes good = serialize(solid);
  std::uint64_t state_size = 0;
  for (int i = 0; i < 8; ++i) state_size = (state_size << 8) | static_cast<unsigned char>(good[16 + static_cast<std::size_t>(i)]);
  std::mt19937 rng(11);
  int accepted = 0;
  for (int i = 0; i < 1500; ++i) {
    const Bytes damaged = with_checksum(mutate(good, 40, 40 + static_cast<std::size_t>(state_size), rng));
    try {
      (void)deserialize(damaged);
      ++accepted;
    } catch (const Error&) {
    }
  }
  CHECK(accepted < 1500);
}

TEST_CASE("fuzz: a damaged .scadbrep manifest or header is rejected cleanly") {
  const TopoDS_Shape box = BRepPrimAPI_MakeBox(1, 2, 3).Solid();
  RegionSource source;
  source.name = "b.step";
  source.byte_length = 1;
  source.content_hash = sha256_tagged("x");
  const Bytes good = make_region_artifact(box, RegionRootKind::Solid, source);
  std::uint64_t manifest_size = 0;
  for (int i = 0; i < 8; ++i) manifest_size = (manifest_size << 8) | static_cast<unsigned char>(good[16 + static_cast<std::size_t>(i)]);
  std::mt19937 rng(13);
  for (int i = 0; i < 1500; ++i) {
    // The payload stays intact (its digest is in the manifest), so OCCT only ever sees valid bytes.
    const Bytes damaged = mutate(good, 0, 32 + static_cast<std::size_t>(manifest_size), rng);
    try {
      (void)decode_artifact(damaged);
    } catch (const Error&) {
    }
  }
}

TEST_CASE("fuzz: STL readers survive garbage") {
  const std::string ascii =
      "solid t\n facet normal 0 0 1\n  outer loop\n   vertex 0 0 0\n   vertex 1 0 0\n   vertex 0 1 0\n  endloop\n"
      " endfacet\nendsolid t\n";
  std::string binary(84, '\0');
  binary[80] = 1;
  binary.append(50, '\x11');
  std::mt19937 rng(17);
  for (int i = 0; i < 1500; ++i) {
    for (const std::string& seed : {ascii, binary}) {
      try {
        (void)read_stl_bytes(mutate(seed, 0, seed.size(), rng));
      } catch (const Error&) {
      }
    }
  }
  std::uniform_int_distribution<int> byte(0, 255);
  for (int i = 0; i < 300; ++i) {
    std::string noise(static_cast<std::size_t>(rng() % 400), '\0');
    for (char& c : noise) c = static_cast<char>(byte(rng));
    try {
      (void)read_stl_bytes(noise);
    } catch (const Error&) {
    }
  }
}

TEST_CASE("an STL with a huge declared count is refused without allocating it") {
  std::string lying(84, '\0');
  lying[83] = '\x7f';  // count = 0x7f000000 but no data follows
  CHECK_THROWS_AS((void)read_stl_bytes(lying), Error);
}
