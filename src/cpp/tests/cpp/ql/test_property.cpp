#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/property.hpp"

using namespace scad;
using namespace scad::ql;

namespace {

// The box face whose outward normal is `axis`'s positive direction (0=x, 1=y, 2=z), or the negative one.
Face face_facing(const Solid& solid, int axis, bool positive) {
  for (const Face& f : solid.faces()) {
    const Vec3 n = f.normal_at();
    const double component = axis == 0 ? n.x : (axis == 1 ? n.y : n.z);
    if (component * (positive ? 1.0 : -1.0) > 0.9)
      return f;
  }
  FAIL("no such face");
  return solid.faces().front();
}

double number(const std::optional<Value>& v) {
  return v.value().as_double();
}

}  // namespace

TEST_CASE("metadata paths walk nested objects and treat null as absent") {
  Value root = Value::object();
  Value geo = Value::object();
  Value size = Value::object();
  size.set("x", 2.0);
  geo.set("size", size);
  geo.set("nothing", Value());
  root.set("geo", geo);
  CHECK(MetadataPath("geo.size.x").find(root)->as_double() == 2.0);
  CHECK(MetadataPath("geo.size.y").find(root) == nullptr);
  CHECK(MetadataPath("geo.nothing").find(root) == nullptr);
  CHECK(MetadataPath("geo.size.x.z").find(root) == nullptr);
  CHECK(MetadataPath("").find(root) == nullptr);
}

TEST_CASE("built-in properties of faces, edges, solids and vertices") {
  const Solid box = ql_test::box(2, 3, 4);
  const Face top = face_facing(box, 2, true);
  CHECK(number(lookup_property(top, "geom.area")) == doctest::Approx(6.0));
  CHECK(number(lookup_property(top, "geom.normal.z")) == doctest::Approx(1.0));
  CHECK(number(lookup_property(top, "geom.center.z")) == doctest::Approx(4.0));
  CHECK(number(lookup_property(top, "geom.center.x")) == doctest::Approx(1.0));
  CHECK(lookup_property(top, "geom.type")->as_string() == "PLANE");
  CHECK(lookup_property(top, "geom.family")->as_string() == "surface");
  CHECK(lookup_property(top, "topo.kind")->as_string() == "face");
  CHECK(number(lookup_property(top, "geom.bbox.max.z")) == 4.0);
  CHECK(number(lookup_property(top, "geom.bbox.min.x")) == 0.0);
  CHECK(number(lookup_property(box, "geom.volume")) == doctest::Approx(24.0));
  CHECK(lookup_property(box, "geom.family")->as_string() == "body");

  const Edge edge = box.edges().front();
  CHECK(lookup_property(edge, "geom.type")->as_string() == "LINE");
  CHECK(lookup_property(edge, "geom.family")->as_string() == "curve");
  CHECK(number(lookup_property(edge, "geom.length")) > 1.9);

  const Vertex vertex = edge.start_vertex();
  CHECK(lookup_property(vertex, "geom.family")->as_string() == "point");
  CHECK(lookup_property(vertex, "geom.center.x").has_value());
  CHECK(lookup_property(vertex, "topo.kind")->as_string() == "vertex");
}

TEST_CASE("properties that do not apply to a kind are missing, not zero") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK_FALSE(lookup_property(box, "geom.area").has_value());
  CHECK_FALSE(lookup_property(box, "geom.length").has_value());
  CHECK_FALSE(lookup_property(box, "geom.normal.z").has_value());
  CHECK_FALSE(lookup_property(box, "geom.center.z").has_value());  // a solid has no centre in QL
  CHECK_FALSE(lookup_property(box, "geom.type").has_value());
  CHECK_FALSE(lookup_property(box.faces().front(), "geom.volume").has_value());
  CHECK_FALSE(lookup_property(box.faces().front(), "geom.length").has_value());
  CHECK_FALSE(lookup_property(box, "geom.nonsense").has_value());
  CHECK_FALSE(lookup_property(box, "").has_value());
}

TEST_CASE("bad axes and bbox fields never resolve") {
  const Solid box = ql_test::box(1, 1, 1);
  const Face face = box.faces().front();
  CHECK_FALSE(lookup_property(face, "geom.center.w").has_value());
  CHECK_FALSE(lookup_property(face, "geom.normal.X").has_value());
  CHECK_FALSE(lookup_property(face, "geom.bbox.min").has_value());
  CHECK_FALSE(lookup_property(face, "geom.bbox.mid.x").has_value());
  // the axis is whatever follows the last dot
  CHECK(lookup_property(face, "geom.center.q.z").has_value());
}

TEST_CASE("a shell has no topo.kind, a wire reports closedness and a loop role") {
  Solid box = ql_test::box(1, 1, 1);
  const Face face = box.faces().front();
  const Wire outer = face.outer_wire();
  CHECK(lookup_property(outer, "geom.closed")->as_bool());
  CHECK(lookup_property(outer, "topo.loop_role")->as_string() == "outer");
  CHECK(lookup_property(outer, "geom.family")->as_string() == "wire");
  CHECK_FALSE(lookup_property(face, "topo.loop_role").has_value());
  CHECK_FALSE(lookup_property(face, "geom.closed").has_value());
}

TEST_CASE("metadata wins over the built-in of the same path; meta. reads metadata only") {
  const Solid box = ql_test::box(1, 1, 1);
  Face face = box.faces().front();
  face.set_metadata("geo", Value::object());
  Value geom = Value::object();
  geom.set("type", "CUSTOM");
  face.set_metadata("geom", geom);
  CHECK(lookup_property(face, "geom.type")->as_string() == "CUSTOM");
  CHECK(lookup_property(face, "meta.geom.type")->as_string() == "CUSTOM");
  CHECK_FALSE(lookup_property(face, "meta.geom.area").has_value());  // the built-in is not consulted
  CHECK(lookup_property(face, "geom.area").has_value());
  CHECK_FALSE(lookup_property(face, "meta.").has_value());
}

TEST_CASE("resolvers answer for their prefix, longest prefix first") {
  const Solid box = ql_test::box(1, 1, 1);
  const Face face = box.faces().front();
  register_property_resolver("custom.", [](const Shape&, std::string_view path) -> std::optional<Value> {
    if (path == "custom.answer")
      return Value(42);
    return std::nullopt;
  });
  register_property_resolver("custom.deep.", [](const Shape&, std::string_view path) -> std::optional<Value> {
    if (path == "custom.deep.answer")
      return Value("deep");
    return std::nullopt;
  });
  CHECK(lookup_property(face, "custom.answer")->as_int() == 42);
  CHECK(lookup_property(face, "custom.deep.answer")->as_string() == "deep");
  CHECK_FALSE(lookup_property(face, "custom.other").has_value());

  // a resolver may decline; the next one (and finally the built-ins) is asked
  register_property_resolver("geom.",
                             [](const Shape&, std::string_view) -> std::optional<Value> { return std::nullopt; });
  CHECK(lookup_property(face, "geom.type")->as_string() == "PLANE");

  // registering a prefix again replaces its resolver
  register_property_resolver("custom.",
                             [](const Shape&, std::string_view) -> std::optional<Value> { return Value(7); });
  CHECK(lookup_property(face, "custom.answer")->as_int() == 7);

  unregister_property_resolver("custom.");
  unregister_property_resolver("custom.deep.");
  unregister_property_resolver("geom.");
  unregister_property_resolver("not.registered.");
  CHECK_FALSE(lookup_property(face, "custom.answer").has_value());
  CHECK_THROWS_AS(register_property_resolver("", nullptr), ValueError);
}

TEST_CASE("centre rules: edges and faces by centre of mass, vertices by position, others none") {
  const Solid box = ql_test::box(2, 2, 2);
  const Face face = face_facing(box, 2, true);
  CHECK(center_of(face)->z == doctest::Approx(2.0));
  const Edge edge = box.edges().front();
  CHECK(center_of(edge).has_value());
  CHECK(center_of(edge.start_vertex()).has_value());
  CHECK_FALSE(center_of(box).has_value());
  CHECK_FALSE(center_of(face.outer_wire()).has_value());
}

TEST_CASE("geometry types of a cylinder") {
  const Solid cyl = ql_test::cylinder(2, 5);
  int planes = 0, cylinders = 0, circles = 0, lines = 0;
  for (const Face& f : cyl.faces()) {
    const auto type = geom_type(f);
    planes += type == "PLANE";
    cylinders += type == "CYLINDER";
  }
  for (const Edge& e : cyl.edges()) {
    const auto type = geom_type(e);
    circles += type == "CIRCLE";
    lines += type == "LINE";
  }
  CHECK(planes == 2);
  CHECK(cylinders == 1);
  CHECK(circles == 2);
  CHECK(lines == 1);  // the seam
  CHECK_FALSE(geom_type(cyl).has_value());
}

TEST_CASE("an evaluation context memoises measurements per shape and answers like the free functions") {
  const Solid box = ql_test::box(2, 3, 4, {1, 1, 1});
  const Face top = face_facing(box, 2, true);
  const EvalContext ctx;

  const auto first = ctx.center(top);
  const auto again = ctx.center(top);
  REQUIRE(first.has_value());
  CHECK(*first == *again);
  CHECK(*first == *center_of(top));
  CHECK(ctx.center(box) == std::nullopt);

  CHECK(ctx.measure(top, Measure::Area).value() == doctest::Approx(6.0));
  CHECK(ctx.measure(top, Measure::Length) == std::nullopt);
  CHECK(ctx.measure(box, Measure::Volume).value() == doctest::Approx(24.0));
  CHECK(ctx.measure(box.edges().front(), Measure::Length).value() > 1.9);
  CHECK(ctx.normal(top).value().z == doctest::Approx(1.0));
  CHECK(ctx.normal(box) == std::nullopt);
  CHECK(ctx.bbox(top).zmax == doctest::Approx(5.0));

  // a handle to the same entity hits the same memo; a different entity does not
  const Face other_handle = face_facing(box, 2, true);
  CHECK(ctx.center(other_handle) == first);
  CHECK(ctx.center(face_facing(box, 2, false))->z == doctest::Approx(1.0));
}
