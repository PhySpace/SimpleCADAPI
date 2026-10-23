#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/key.hpp"

using namespace scad;
using namespace scad::ql;

TEST_CASE("value(): metadata first, then the geo.* measurements, else the default") {
  Solid box = ql_test::box(2, 3, 4);
  Value geo_data = Value::object();
  geo_data.set("height", 9.5);
  box.set_metadata("geo", geo_data);
  CHECK(value("geo.height")(box).as_double() == 9.5);
  CHECK(geo("height")(box).as_double() == 9.5);
  CHECK(value("geo.volume")(box).as_double() == doctest::Approx(24.0));
  CHECK(value("geo.area")(box).is_null());           // a solid has no area
  CHECK(value("geo.area", Value(-1))(box).as_int() == -1);
  CHECK(value("geo.missing", Value("none"))(box).as_string() == "none");
  CHECK(value("other.thing")(box).is_null());

  const Face face = box.faces().front();
  CHECK(value("geo.area")(face).as_double() > 0);
  CHECK(value("geo.length")(box.edges().front()).as_double() > 0);
}

TEST_CASE("key(): the property language with a default for missing") {
  const Solid box = ql_test::box(2, 3, 4);
  Face top = box.faces().front();
  for (const Face& f : box.faces())
    if (f.normal_at().z > 0.9) top = f;
  CHECK(key("geom.center.z")(top).as_double() == doctest::Approx(4.0));
  CHECK(key("geom.normal.z")(top).as_double() == doctest::Approx(1.0));
  CHECK(key("geom.center.z")(box).is_null());
  CHECK(key("geom.center.z", Value(0))(box).as_int() == 0);
  CHECK(center_axis("Z ")(top).as_double() == doctest::Approx(4.0));
}

TEST_CASE("center_axis validates its axis; a center_axis payload keeps the kind") {
  CHECK_THROWS_WITH_AS((void)center_axis("w"), "axis must be one of 'x', 'y', 'z'", ValueError);
  CHECK(center_axis("x").to_value().dump() == R"({"kind":"property","data":{"path":"geom.center.x","default":null}})");

  Value data = Value::object();
  data.set("axis", "Y");
  const Key raw("center_axis", data);
  const Solid box = ql_test::box(2, 4, 6);
  CHECK(raw(box.faces().front()).is_number());
  CHECK(raw(box).is_null());

  Value bad = Value::object();
  bad.set("axis", "q");
  CHECK_THROWS_WITH_AS((void)Key("center_axis", bad)(box.faces().front()), "unsupported axis: q", ValueError);
}

TEST_CASE("keys serialize and restore; an unknown kind fails only when evaluated") {
  const Key k = geo("area", Value(0.0));
  CHECK(Key::from_value(k.to_value()) == k);
  CHECK(k.to_value().dump() == R"({"kind":"value","data":{"path":"geo.area","default":0}})");

  const Key odd("mystery", Value::object());
  const Solid box = ql_test::box(1, 1, 1);
  CHECK_THROWS_WITH_AS((void)odd(box), "unsupported key kind: mystery", ValueError);

  CHECK_THROWS_AS((void)Key("value", Value::object()), Exception);  // KeyError: 'path'
  Value no_kind = Value::object();
  CHECK_THROWS_AS((void)Key::from_value(no_kind), Exception);
}
