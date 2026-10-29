#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/predicate.hpp"

using namespace scad;
using namespace scad::ql;

namespace {

Value track_of(std::initializer_list<Value::Member> members) {
  Value track = Value::object();
  for (const auto& [name, item] : members)
    track.set(name, item);
  return track;
}

Value list_of(std::initializer_list<const char*> items) {
  Value out = Value::array();
  for (const char* item : items)
    out.push_back(item);
  return out;
}

Face first_face(const Solid& solid) {
  return solid.faces().front();
}

// A local binding the way operators leave one behind: evidence data names its source.
TagBinding projected_binding(std::string tag_name, std::string field, std::string source) {
  TagBinding b;
  b.tag = std::move(tag_name);
  b.policy.mut().producer.kind = TagProducerKind::AutoRule;
  b.policy.mut().producer.rule_id = "test.projection";
  b.policy.mut().producer.rule_version = "1.0";
  b.policy.mut().propagation.lineage = LineagePolicy::None;
  b.evidence.mut().kind = TagEvidenceKind::LegacySnapshot;
  b.evidence.mut().data.set(std::move(field), std::move(source));
  b.certainty = TagCertainty::Proven;
  b.lifecycle = TagLifecycle::Snapshot;
  b.binding_id = new_binding_id();
  return b;
}

Value payload_leaf(const char* kind, Value data = Value::object()) {
  Value v = Value::object();
  v.set("kind", kind);
  v.set("data", std::move(data));
  v.set("children", Value::array());
  return v;
}

}  // namespace

// ---- tags ---------------------------------------------------------------------------------------
TEST_CASE("tag: exact match, trailing wildcard, and nothing for an invalid name") {
  Solid box = ql_test::box(1, 1, 1);
  box.apply_tag("role.mounting_surface", false);
  CHECK(tag("role.mounting_surface")(box));
  CHECK(tag("role.*")(box));
  CHECK(tag("*")(box));
  CHECK_FALSE(tag("role.other")(box));
  CHECK_FALSE(tag("Role.Mounting_Surface")(box));  // not a tag name: cannot match, and must not throw
  CHECK_FALSE(tag("state.*")(box));
}

TEST_CASE("tag: scopes distinguish local from inherited tags") {
  Solid box = ql_test::box(1, 1, 1);
  box.apply_tag("role.body", /*propagate=*/true);
  const Face face = first_face(box);
  CHECK_FALSE(tag("role.body", TagScope::Local)(face));
  CHECK(tag("role.body", TagScope::Inherited)(face));
  CHECK(tag("role.body", "effective")(face));
  CHECK(tag("role.body", " Inherited ")(face));
}

TEST_CASE("tag: construction validates the pattern and the scope") {
  CHECK_THROWS_WITH_AS((void)tag("   "), "pattern must be non-empty", ValueError);
  CHECK_THROWS_WITH_AS((void)tag("a*b"), "only trailing '*' wildcard is supported", ValueError);
  CHECK_THROWS_AS((void)tag("a", "sideways"), ValueError);
  CHECK(tag("  role.x  ").data().find("pattern")->as_string() == "role.x");
}

TEST_CASE("tag: the face tags autotagging leaves behind") {
  Solid box = ql_test::box(1, 2, 3);
  box.auto_tag_faces("box");
  int top = 0, any_face = 0;
  for (const Face& f : box.faces()) {
    top += tag("face.top")(f);
    any_face += tag("face.*")(f);
  }
  CHECK(top == 1);
  CHECK(any_face == 6);
}

// ---- metadata -------------------------------------------------------------------------------------
TEST_CASE("meta: equality and ordering on nested metadata") {
  Solid box = ql_test::box(2, 3, 4);
  Value geo = Value::object();
  geo.set("type", "box");
  Value size = Value::object();
  size.set("x", 2.0);
  geo.set("size", size);
  box.set_metadata("geo", geo);
  CHECK(meta("geo.type", "==", "box")(box));
  CHECK_FALSE(meta("geo.type", "!=", "box")(box));
  CHECK(meta("geo.size.x", ">", 1.0)(box));
  CHECK(meta("geo.size.x", ">=", 2)(box));
  CHECK_FALSE(meta("geo.size.x", "<", 2)(box));
  CHECK(meta("geo.size.x", "<=", 2)(box));
  CHECK_FALSE(meta("geo.size.x", ">", "text")(box));  // unrelated types: false, no error
}

TEST_CASE("meta: a missing value is None, equal to None and different from everything else") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK(meta("geo.absent", "==", Value())(box));
  CHECK(meta("geo.absent", "!=", 1)(box));
  CHECK_FALSE(meta("geo.absent", "==", 1)(box));
  CHECK_FALSE(meta("geo.absent", ">", 1)(box));
  CHECK_FALSE(meta("geo.absent", "<", 1)(box));
}

TEST_CASE("meta: an unsupported operator surfaces only when there is a value to compare") {
  Solid box = ql_test::box(1, 1, 1);
  box.set_metadata("n", 1);
  CHECK_FALSE(meta("missing", "~", 1)(box));
  CHECK_THROWS_WITH_AS((void)meta("n", "~", 1)(box), "unsupported op: ~", ValueError);
  CHECK(meta("n", "  ==  ", 1)(box));  // factories strip the operator
}

// ---- properties -----------------------------------------------------------------------------------------
TEST_CASE("prop: a missing property never matches, whatever the operator") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK_FALSE(prop("geom.area", "==", 1)(box));
  CHECK_FALSE(prop("geom.area", "!=", 1)(box));
  CHECK(prop("geom.volume", ">", 0.99)(box));
}

TEST_CASE("prop: geometry compares exactly, integer constants against float measurements") {
  const Solid a = ql_test::box(2, 2, 2, {3, 0, 4});
  const Solid b = ql_test::box(2, 2, 2, {8, 0, 4});
  const Predicate p = and_({prop("geom.bbox.min.x", "==", 8), prop("geom.bbox.max.z", "==", 6)});
  CHECK_FALSE(p(a));
  CHECK(p(b));
  CHECK(or_({prop("geom.bbox.min.x", "==", 3), prop("geom.bbox.min.x", "==", 8)})(a));
  CHECK(not_(prop("geom.bbox.min.x", "==", 3))(b));
}

TEST_CASE("curve_type and surface_type are geom.type equality, case-insensitively") {
  const Solid cyl = ql_test::cylinder(1, 2);
  int circles = 0, cylinders = 0;
  for (const Edge& e : cyl.edges())
    circles += curve_type("circle")(e);
  for (const Face& f : cyl.faces())
    cylinders += surface_type("Cylinder")(f);
  CHECK(circles == 2);
  CHECK(cylinders == 1);
  CHECK(curve_type("circle").data().find("value")->as_string() == "CIRCLE");
  CHECK(curve_type("circle").data().find("path")->as_string() == "geom.type");
}

// ---- tracking evidence --------------------------------------------------------------------------------
TEST_CASE("operation_event: names, aliases and events under track metadata") {
  Solid box = ql_test::box(1, 1, 1);
  Face face = first_face(box);
  face.set_metadata("track", track_of({{"op", "make_cut_rsolid"}, {"event", "generated"}}));
  CHECK(op("cut", "generated")(face));
  CHECK(op("make_cut_rsolid", "generated")(face));
  CHECK(op("op.cut")(face));
  CHECK(op("cut")(face));
  CHECK_FALSE(op("cut", "modified")(face));
  CHECK_FALSE(op("union")(face));

  face.set_metadata("track", track_of({{"operation", "translate"}, {"events", list_of({"modified", "preserved"})}}));
  CHECK(op("make_translate_rsolid", "modified")(face));
  CHECK(op("translate", "preserved")(face));
  CHECK_FALSE(op("translate", "generated")(face));

  face.set_metadata("track", track_of({{"op", "make_cut_rsolid"}, {"events", Value::array()}}));
  CHECK_FALSE(op("cut")(face));  // an explicit empty list means no events at all
}

TEST_CASE("operation_event: wrapper suffixes are aliases, flat tags are not evidence") {
  Solid box = ql_test::box(1, 1, 1);
  Face face = first_face(box);
  face.set_metadata("track", track_of({{"op", "make_box_rsolid"}, {"event", "generated"}}));
  CHECK(op("box")(face));
  CHECK(op("make_box_rsolid")(face));
  CHECK(op("make_box")(face));  // shares the alias "box"
  CHECK_FALSE(op("make_cube")(face));

  Face other = box.faces()[1];
  other.add_tag("op.cut.generated");
  other.add_tag("origin.tool");
  CHECK_FALSE(op("cut", "generated")(other));
  CHECK_FALSE(origin("tool")(other));
}

TEST_CASE("origin_role and output_role read the plural list, else the singular") {
  Solid box = ql_test::box(1, 1, 1);
  Face face = first_face(box);
  face.set_metadata("track",
                    track_of({{"origin_roles", list_of({"body", "tool"})}, {"result_role", "extrude.first_cap"}}));
  CHECK(origin("tool")(face));
  CHECK(origin_role("body")(face));
  CHECK_FALSE(origin("profile")(face));
  CHECK(output_role("Extrude.First_Cap")(face));  // lower-cased at construction
  CHECK_FALSE(output_role("extrude.last_cap")(face));

  face.set_metadata("track", track_of({{"origin_role", "body"}}));
  CHECK(origin("body")(face));
  CHECK_FALSE(origin("tool")(face));
  face.set_metadata("track", Value("not an object"));
  CHECK_FALSE(origin("body")(face));
}

TEST_CASE("role is the role.<name>.* tag family") {
  Solid box = ql_test::box(1, 1, 1);
  Face face = first_face(box);
  face.add_tag("role.section.face");
  CHECK(role("section")(face));
  CHECK_FALSE(role("other")(face));
  CHECK(role("section").data().find("pattern")->as_string() == "role.section.*");
}

TEST_CASE("source_binding and source_topology match the evidence of a local binding") {
  Solid box = ql_test::box(1, 1, 1);
  Face face = first_face(box);
  face.add_binding(projected_binding("role.x", "source_binding_id", "tag_binding_aaa"));
  face.add_binding(projected_binding("role.y", "source_topo_id", "face_7"));
  CHECK(source_binding("tag_binding_aaa")(face));
  CHECK_FALSE(source_binding("tag_binding_bbb")(face));
  CHECK(source_topology("face_7")(face));
  CHECK_FALSE(source_topology("face_8")(face));
  CHECK_FALSE(source_topology("face_7")(box.faces()[1]));
}

TEST_CASE("construction helpers reject empty names with the Python messages") {
  CHECK_THROWS_WITH_AS((void)operation_event(" "), "op_name must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)operation_event("cut", ""), "event must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)origin_role(""), "role_name must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)output_role(""), "role_name must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)source_binding(" "), "binding_id must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)source_topology(""), "topo_id must be a non-empty string", ValueError);
}

// ---- composition ----------------------------------------------------------------------------------------
TEST_CASE("and / or / not short-circuit and nest") {
  Solid box = ql_test::box(1, 1, 1);
  box.apply_tag("role.mounting_surface", false);
  box.apply_tag("state.debug", false);
  Value geo = Value::object();
  geo.set("type", "box");
  box.set_metadata("geo", geo);

  CHECK_FALSE(and_({meta("geo.type", "==", "box"), tag("role.mounting_surface"), not_(tag("state.*"))})(box));
  CHECK(and_({meta("geo.type", "==", "box"), tag("role.mounting_surface")})(box));
  CHECK(or_({tag("nope"), tag("state.*")})(box));
  CHECK_FALSE(or_({tag("nope"), tag("also.nope")})(box));
  CHECK(and_({})(box));  // all([]) is true
  CHECK_FALSE(or_({})(box));
  CHECK(not_(not_(tag("role.*")))(box));
  // deep nesting keeps child boundaries straight in the flattened program
  CHECK(and_({or_({tag("a"), and_({tag("role.*"), not_(tag("zzz"))})}), not_(or_({tag("q"), tag("r")}))})(box));
}

// ---- serialization ------------------------------------------------------------------------------------------
TEST_CASE("predicates serialize to the Python payload and round-trip") {
  const Predicate p = and_({tag("role.x", TagScope::Inherited), not_(prop("geom.area", ">", 2.5)),
                            or_({meta("a.b", "==", "v"), op("cut", "modified"), origin("tool"), output_role("a.b"),
                                 source_binding("tag_binding_1"), source_topology("face_2")})});
  const Value payload = p.to_value();
  CHECK(payload.find("kind")->as_string() == "and");
  CHECK(payload.find("children")->size() == 3);
  const Value& first = payload.find("children")->as_array()[0];
  CHECK(first.dump() == R"({"kind":"tag","data":{"pattern":"role.x","scope":"inherited"},"children":[]})");
  CHECK(Predicate::from_value(payload) == p);
  CHECK(Predicate::from_value(payload).to_value() == payload);
}

TEST_CASE("a restored predicate evaluates like the original") {
  const Solid box = ql_test::box(2, 3, 4);
  const Predicate p = and_({surface_type("PLANE"), prop("geom.normal.z", ">", 0.9)});
  const Predicate q = Predicate::from_value(p.to_value());
  int hits = 0;
  for (const Face& f : box.faces()) {
    CHECK(p(f) == q(f));
    hits += q(f);
  }
  CHECK(hits == 1);
}

TEST_CASE("curve_type / surface_type payloads compare the kernel type directly") {
  Value data = Value::object();
  data.set("value", "cylinder");
  const Predicate p = Predicate::from_value(payload_leaf("surface_type", data));
  const Solid cyl = ql_test::cylinder(1, 2);
  int hits = 0;
  for (const Face& f : cyl.faces())
    hits += p(f);
  CHECK(hits == 1);
  CHECK_FALSE(p(cyl));
}

TEST_CASE("from_value reports malformed payloads with the Python messages") {
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(Value(1)), "predicate payload must be an object", ValueError);
  Value extra = payload_leaf("tag");
  extra.set("junk", 1);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(extra), "predicate payload contains unknown fields", ValueError);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(Value::object()), "predicate kind must be a non-empty string",
                       ValueError);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("bogus")), "unsupported predicate kind: bogus",
                       ValueError);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("tag")),
                       "predicate 'tag' is missing required data: pattern", ValueError);
  Value only_value = Value::object();
  only_value.set("value", 1);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("meta", only_value)),
                       "predicate 'meta' is missing required data: op, path", ValueError);
  Value colored = Value::object();
  colored.set("pattern", "x");
  colored.set("color", "red");
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("tag", colored)),
                       "predicate 'tag' contains unknown data: color", ValueError);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("and")), "predicate 'and' requires at least one child",
                       ValueError);
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(payload_leaf("not")), "predicate 'not' requires exactly one child",
                       ValueError);
  Value role_data = Value::object();
  role_data.set("role", "x");
  Value with_children = payload_leaf("origin_role", role_data);
  with_children.set("children", Value(Value::Array{payload_leaf("and")}));
  CHECK_THROWS_WITH_AS((void)Predicate::from_value(with_children), "predicate 'origin_role' cannot contain children",
                       ValueError);
}
