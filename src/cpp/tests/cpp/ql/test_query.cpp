#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/ql.hpp"

using namespace scad;

TEST_CASE("select: where / order_by / limit / first over shapes you hold") {
  std::vector<Solid> cylinders;
  for (const double h : {1.0, 3.0, 2.0}) {
    Solid c = ql_test::cylinder(1, h);
    Value geo = Value::object();
    geo.set("height", h);
    c.set_metadata("geo", geo);
    cylinders.push_back(c);
  }
  const auto tallest = ql::select(cylinders).order_by(ql::value("geo.height"), true).first();
  REQUIRE(tallest.has_value());
  CHECK(tallest->get_metadata("geo").find("height")->as_double() == 3.0);

  CHECK(ql::select(cylinders).where(ql::meta("geo.height", ">", 1.5)).all().size() == 2);
  CHECK(ql::select(cylinders).limit(0).all().empty());
  CHECK(ql::select(cylinders).limit(-3).all().empty());
  CHECK(ql::select(cylinders).limit(2).all().size() == 2);
  CHECK(ql::select(cylinders).limit(99).all().size() == 3);
  CHECK_FALSE(ql::select(std::vector<Solid>{}).first().has_value());
}

TEST_CASE("select: where takes any callable; order_by is stable with None last") {
  const Solid box = ql_test::box(1, 2, 3);
  const auto faces = box.faces();
  const auto flat = ql::select(faces).where([](const Shape& s) { return Face(s).normal_at().z > 0.9; }).all();
  CHECK(flat.size() == 1);

  // faces without a geo.* value after the ones that have it; ties keep their order
  Face a = faces[0], b = faces[1], c = faces[2];
  b.set_metadata("rank", 1);
  c.set_metadata("rank", 1);
  const auto ordered = ql::select(std::vector<Face>{a, b, c}).order_by(ql::value("rank")).all();
  CHECK(ordered[0].same_entity(b));
  CHECK(ordered[1].same_entity(c));
  CHECK(ordered[2].same_entity(a));
  const auto reversed = ql::select(std::vector<Face>{a, b, c}).order_by(ql::value("rank"), true).all();
  CHECK(reversed[0].same_entity(a));  // None sorts first when descending
  CHECK(reversed[1].same_entity(b));
  CHECK(reversed[2].same_entity(c));
}

TEST_CASE("select: keys of unrelated types cannot be ordered") {
  const Solid box = ql_test::box(1, 2, 3);
  Face a = box.faces()[0], b = box.faces()[1];
  a.set_metadata("rank", 1);
  b.set_metadata("rank", "high");
  CHECK_THROWS_AS((void)ql::select(std::vector<Face>{a, b}).order_by(ql::value("rank")), TypeError);
}
