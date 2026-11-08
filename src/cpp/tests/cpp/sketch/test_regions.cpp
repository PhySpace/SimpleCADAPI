// Regions of a sketch: which closed profile lies inside which (inspect_sketch_rsketchprofiles), one face per region
// (make_faces_from_sketch_rfacelist), and the profile index faces and wires share.
#include "doctest.h"

#include <cmath>
#include <functional>
#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

using namespace scad;

namespace {

// A 40 x 20 plate with a circle in it, a second 20 x 20 square apart, and an open chain drawn first.
Sketch plate_and_square() {
  Sketch s = make_sketch_rsketch("regions");
  const std::vector<std::pair<std::string, std::pair<double, double>>> points{
      {"z1", {-20, 0}}, {"z2", {-10, 0}}, {"a", {0, 0}},   {"b", {40, 0}},  {"c", {40, 20}}, {"d", {0, 20}},
      {"e", {60, 0}},   {"f", {80, 0}},   {"g", {80, 20}}, {"h", {60, 20}}, {"o", {10, 10}}};
  for (const auto& [id, xy] : points)
    s = add_point_rsketch(s, id, xy.first, xy.second);
  s = add_line_rsketch(s, "zz", "z1", "z2");
  s = add_line_rsketch(s, "l0", "a", "b");
  s = add_line_rsketch(s, "l1", "b", "c");
  s = add_line_rsketch(s, "l2", "c", "d");
  s = add_line_rsketch(s, "l3", "d", "a");
  s = add_line_rsketch(s, "m0", "e", "f");
  s = add_line_rsketch(s, "m1", "f", "g");
  s = add_line_rsketch(s, "m2", "g", "h");
  s = add_line_rsketch(s, "m3", "h", "e");
  return add_circle_rsketch(s, "k", "o", 4.0);
}

std::string failure_text(const std::function<void()>& call) {
  try {
    call();
  } catch (const Error& e) {
    return e.guidance().technical_details;
  }
  return {};
}

}  // namespace

TEST_CASE("profiles report their nesting and the regions") {
  const Value info = inspect_sketch_rsketchprofiles(plate_and_square());
  const Value::Array& profiles = info.find("profiles")->as_array();
  // circles first (k: 0), then the edge components in entity order (zz: 1, l0: 2, m0: 3)
  REQUIRE(profiles.size() == 4);
  CHECK(profiles[0].find("parent")->as_int() == 2);
  CHECK(profiles[0].find("depth")->as_int() == 1);
  CHECK(profiles[1].find("parent")->is_null());  // the open chain
  CHECK(profiles[2].find("depth")->as_int() == 0);
  const Value::Array& regions = info.find("regions")->as_array();
  REQUIRE(regions.size() == 2);
  CHECK(regions[0].find("outer")->as_int() == 2);
  CHECK(regions[0].find("holes")->as_array().size() == 1);
  CHECK(regions[1].find("outer")->as_int() == 3);
}

TEST_CASE("one face per region, with its holes; a hole or an open chain is refused") {
  const Sketch s = plate_and_square();
  const std::vector<Face> faces = make_faces_from_sketch_rfacelist(s);
  REQUIRE(faces.size() == 2);
  CHECK(std::abs(faces[0].area() - (800.0 - kPi * 16.0)) < 1e-3);
  CHECK(std::abs(faces[1].area() - 400.0) < 1e-6);
  const std::vector<Face> one =
      make_faces_from_sketch_rfacelist(s, std::vector<SketchProfileId>{SketchProfileId("m0")});
  CHECK(one.size() == 1);
  CHECK(failure_text([&] { make_faces_from_sketch_rfacelist(s, std::vector<SketchProfileId>{0}); }).find("is a hole") !=
        std::string::npos);
  CHECK(failure_text([&] {
          make_faces_from_sketch_rfacelist(s, std::vector<SketchProfileId>{1});
        }).find("open chain") != std::string::npos);
}

TEST_CASE("a face takes the index inspect_sketch_rsketchprofiles lists, open chains counted") {
  const Sketch s = plate_and_square();
  CHECK(std::abs(make_face_from_sketch_rface(s, 3).area() - 400.0) < 1e-6);
  CHECK(failure_text([&] { make_face_from_sketch_rface(s, 1); }).find("is an open chain") != std::string::npos);
}
