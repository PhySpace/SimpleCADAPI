#include <algorithm>

#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/ql.hpp"
#include "scad/topo/recorder.hpp"

using namespace scad;

namespace {

Solid tagged_box(double x, double y, double z) {
  Solid box = ql_test::box(x, y, z);
  box.auto_tag_faces("box");
  return box;
}

std::vector<double> centers(const std::vector<Shape>& shapes, char axis) {
  std::vector<double> out;
  for (const Shape& s : shapes) {
    const Vec3 c = s.center();
    out.push_back(axis == 'x' ? c.x : (axis == 'y' ? c.y : c.z));
  }
  return out;
}

bool same_entities(const std::vector<Shape>& a, const std::vector<Shape>& b) {
  return a.size() == b.size() &&
         std::equal(a.begin(), a.end(), b.begin(), [](const Shape& x, const Shape& y) { return x.same_entity(y); });
}

std::string error_text(const std::function<void()>& body) {
  try {
    body();
  } catch (const Error& e) {
    return e.what();
  } catch (const std::exception& e) {
    return std::string("other: ") + e.what();
  }
  return "no error";
}

}  // namespace

// ---- candidates by scope -----------------------------------------------------------------------------
TEST_CASE("a solid scope offers faces, unique edges, vertices and itself") {
  const Solid box = ql_test::box(2, 3, 4);
  CHECK(ql::faces().resolve(box).size() == 6);
  CHECK(ql::edges().resolve(box).size() == 12);
  CHECK(ql::vertices().resolve(box).size() == 8);
  const auto solids = ql::solids().resolve(box);
  REQUIRE(solids.size() == 1);
  CHECK(solids[0].same_entity(box));
  CHECK(ql_test::ids(ql::faces().resolve(box)) == ql_test::ids(box.faces()));  // enumeration order is the SDK's
}

TEST_CASE("a solid has no wire children; wires come through faces") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK(ql::wires().resolve(box).empty());
  CHECK(ql::faces().boundary("wire").resolve(box).size() == 6);
}

TEST_CASE("a face scope offers its wires, edges and vertices; an edge scope its vertices") {
  const Solid box = ql_test::box(1, 1, 1);
  const Face face = box.faces().front();
  CHECK(ql::wires().resolve(face).size() == 1);
  CHECK(ql::edges().resolve(face).size() == 4);
  CHECK(ql::vertices().resolve(face).size() == 4);
  CHECK(ql::faces().resolve(face).size() == 1);
  CHECK(ql::vertices().resolve(face.edges().front()).size() == 2);
}

TEST_CASE("a scope that cannot offer the kind is a TypeError naming the target") {
  const Solid box = ql_test::box(1, 1, 1);
  const Edge edge = box.edges().front();
  CHECK_THROWS_WITH_AS((void)ql::faces().resolve(edge), "cannot resolve QL selector scope for target_kind=face", TypeError);
  CHECK_THROWS_AS((void)ql::edges().resolve(edge.start_vertex()), TypeError);
  CHECK_THROWS_AS((void)ql::shells().resolve(box), TypeError);
  CHECK_THROWS_AS((void)ql::solids().resolve(box.faces().front()), TypeError);
}

TEST_CASE("a compound scope offers its solids and everything below") {
  const Compound scope = ql_test::compound_of({ql_test::box(1, 1, 1), ql_test::box(1, 1, 1, {5, 0, 0})});
  CHECK(ql::solids().resolve(scope).size() == 2);
  CHECK(ql::faces().resolve(scope).size() == 12);
  CHECK(ql::edges().resolve(scope).size() == 24);
}

TEST_CASE("a list scope is its own candidate set, whatever the kinds in it") {
  const Solid a = ql_test::box(1, 1, 1);
  const Solid b = ql_test::box(2, 2, 2, {8, 0, 0});
  const auto picked = ql::solids().where(ql::prop("geom.bbox.min.x", "==", 8)).exactly(1).resolve(ql::Scope(std::vector<Solid>{a, b}));
  REQUIRE(picked.size() == 1);
  CHECK(picked[0].same_entity(b));
  // faces() over a list of faces: the list, filtered
  const auto faces = a.faces();
  CHECK(ql::faces().where(ql::prop("geom.normal.z", ">", 0.9)).resolve(ql::Scope(faces)).size() == 1);
  CHECK(ql::faces().resolve(ql::Scope(std::vector<Shape>{})).empty());
}

// ---- the pipeline ----------------------------------------------------------------------------------------------
TEST_CASE("the highest planar face of a box") {
  const Solid box = ql_test::box(2, 3, 4);
  const auto picked = ql::faces()
                          .where(ql::prop("geom.type", "==", "PLANE"))
                          .order_by(ql::key("geom.center.z"), true)
                          .take(1)
                          .exactly(1)
                          .resolve(box);
  REQUIRE(picked.size() == 1);
  CHECK(Face(picked[0]).normal_at().z > 0.9);
}

TEST_CASE("order keys apply left to right, ties keep their order, descending flips per key") {
  const Solid box = ql_test::box(2, 2, 2);
  const auto picked = ql::faces().order_by(ql::key("geom.center.z"), true).order_by(ql::key("geom.center.x")).resolve(box);
  const auto z = centers(picked, 'z');
  const auto x = centers(picked, 'x');
  CHECK(z.front() == doctest::Approx(2.0));
  CHECK(z.back() == doctest::Approx(0.0));
  // within the z == 1 band the x coordinates never decrease
  std::vector<double> band;
  for (std::size_t i = 0; i < z.size(); ++i)
    if (z[i] == doctest::Approx(1.0)) band.push_back(x[i]);
  CHECK(band.size() == 4);
  CHECK(std::is_sorted(band.begin(), band.end()));
}

TEST_CASE("shapes whose key is missing sort after the rest, before them when descending") {
  const Solid box = ql_test::box(2, 2, 2);
  Face tagged = box.faces()[3];
  Value rank = Value::object();
  rank.set("n", 1);
  tagged.set_metadata("rank", rank);
  const auto ascending = ql::faces().order_by(ql::value("rank.n")).resolve(box);
  CHECK(ascending.front().same_entity(tagged));
  const auto descending = ql::faces().order_by(ql::value("rank.n"), true).resolve(box);
  CHECK(descending.back().same_entity(tagged));
}

TEST_CASE("take limits after sorting; take(0) with at_least(1) fails") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK(ql::faces().take(2).resolve(box).size() == 2);
  CHECK(ql::faces().take(0).resolve(box).empty());
  CHECK(ql::faces().take(99).resolve(box).size() == 6);
  CHECK_THROWS_AS((void)ql::faces().take(0).at_least(1).resolve(box), Error);
  CHECK_THROWS_AS((void)ql::faces().at_most(1).resolve(box), Error);
  CHECK(ql::faces().at_least(6).at_most(6).exactly(6).resolve(box).size() == 6);
}

TEST_CASE("boundary traversal: top face -> outer wire -> four edges, and it survives serialization") {
  const Solid box = ql_test::box(2, 3, 4);
  const ql::ShapeSelector selector = ql::faces()
                                         .where(ql::prop("geom.normal.z", ">", 0.9))
                                         .order_by(ql::key("geom.center.z"), true)
                                         .take(1)
                                         .exactly(1)
                                         .boundary("wire")
                                         .where(ql::prop("topo.loop_role", "==", "outer"))
                                         .take(1)
                                         .exactly(1)
                                         .boundary("edge")
                                         .exactly(4);
  CHECK(selector.resolve(box).size() == 4);

  const Value payload = selector.to_value();
  CHECK(payload.find("traversal")->find("relation")->as_string() == "boundary");
  CHECK(payload.find("source")->find("traversal")->find("relation")->as_string() == "boundary");
  const ql::ShapeSelector restored = ql::selector_from_value(payload);
  CHECK(restored.resolve(box).size() == 4);
  CHECK(restored == selector);
}

TEST_CASE("boundary traversal over a cut solid") {
  const Solid base = ql_test::cylinder(1.5, 4.0, {0, 0, -2});
  const Solid tool = ql_test::box(4, 4, 4, {-2, -2, 0.25});
  const Solid result = ql_test::cut(base, tool);
  const auto edges = ql::faces()
                         .where(ql::prop("geom.type", "==", "PLANE"))
                         .where(ql::prop("geom.normal.z", ">", 0.9))
                         .order_by(ql::key("geom.center.z"), true)
                         .take(1)
                         .exactly(1)
                         .boundary("wire")
                         .where(ql::prop("topo.loop_role", "==", "outer"))
                         .take(1)
                         .exactly(1)
                         .boundary("edge")
                         .resolve(result);
  CHECK(edges.size() > 0);
}

TEST_CASE("boundary of each kind from a solid, a face and an edge") {
  const Solid box = ql_test::box(1, 1, 1);
  const Face face = box.faces().front();
  CHECK(ql::solids().boundary("edge").resolve(box).size() == 12);
  CHECK(ql::solids().boundary("vertex").resolve(box).size() == 8);
  CHECK(ql::solids().boundary("face").resolve(box).size() == 6);
  CHECK(ql::faces().boundary("vertex").resolve(face).size() == 4);
  CHECK(ql::edges().boundary("vertex").resolve(face).size() == 4);  // shared corners are deduplicated
  CHECK(ql::faces().boundary("solid").resolve(box).empty());        // a face has no solid below it
  CHECK(ql::solids().boundary("solid").resolve(box).size() == 1);
  CHECK(ql::edges().boundary("edge").resolve(face).empty());
}

// ---- incident faces, intersections --------------------------------------------------------------------------
TEST_CASE("incident_to picks the edge two named faces share") {
  const Solid box = tagged_box(4, 2, 3);
  const ql::ShapeSelector top = ql::faces().where(ql::tag("face.top"));
  const ql::ShapeSelector front = ql::faces().where(ql::tag("face.front"));
  const ql::ShapeSelector selector =
      ql::faces().where(ql::tag("face.top")).boundary("edge").incident_to({top, front}, true).incident_face_count(2).exactly(1);
  const auto edges = selector.resolve(box);
  REQUIRE(edges.size() == 1);
  CHECK(ql::selector_from_value(selector.to_value()).resolve(box).size() == 1);
  for (const Face& f : Edge(edges[0]).incident_faces()) {
    CHECK((f.has_tag("face.top") || f.has_tag("face.front")));
  }
}

TEST_CASE("distinct witnesses: one face cannot stand for two selectors") {
  const Solid box = tagged_box(4, 2, 3);
  const ql::ShapeSelector top = ql::faces().where(ql::tag("face.top"));
  const auto shared = ql::edges().incident_to({top, top}, /*distinct=*/false).resolve(box);
  const auto distinct = ql::edges().incident_to({top, top}, /*distinct=*/true).resolve(box);
  CHECK(shared.size() == 4);
  CHECK(distinct.empty());
  // matching must backtrack: the top/front edge needs top for the first selector and front for the second,
  // whichever of its two faces is listed first
  const ql::ShapeSelector top_or_front = ql::faces().where(ql::or_({ql::tag("face.top"), ql::tag("face.front")}));
  const ql::ShapeSelector front = ql::faces().where(ql::tag("face.front"));
  CHECK(ql::edges().incident_to({top_or_front, front}, true).resolve(box).size() == 1);
  CHECK(ql::edges().incident_to({front, top_or_front}, true).resolve(box).size() == 1);
}

TEST_CASE("incident_face_count(exactly) counts distinct incident faces") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK(ql::edges().incident_face_count(2).resolve(box).size() == 12);
  CHECK(ql::edges().incident_face_count(1).resolve(box).empty());
  const Solid cyl = ql_test::cylinder(1, 2);
  // the seam is used twice by the side face but is one incident face; the two circles touch two faces
  const auto seam = ql::edges().where(ql::curve_type("LINE")).resolve(cyl);
  REQUIRE(seam.size() == 1);
  CHECK(ql::edges().where(ql::curve_type("LINE")).incident_face_count(1).resolve(cyl).size() == 1);
  CHECK(ql::edges().where(ql::curve_type("CIRCLE")).incident_face_count(2).resolve(cyl).size() == 2);
}

TEST_CASE("shared_boundary intersects by topology identity") {
  Solid cyl = ql_test::cylinder(2, 3);
  cyl.auto_tag_faces("cylinder");
  const ql::ShapeSelector start = ql::faces().where(ql::tag("face.bottom"));
  const ql::ShapeSelector side = ql::faces().where(ql::tag("face.side"));
  const ql::ShapeSelector shared = start.shared_boundary(side).exactly(1);
  CHECK(shared.resolve(cyl).size() == 1);
  CHECK(ql::selector_from_value(shared.to_value()).resolve(cyl).size() == 1);

  Solid first = ql_test::cylinder(2, 3);
  Solid second = ql_test::cylinder(2, 3);
  first.apply_tag("first.solid", false);
  second.apply_tag("second.solid", false);
  const ql::ShapeSelector in_first = ql::solids().where(ql::tag("first.solid"));
  CHECK(same_entities(in_first.shared_boundary(in_first).resolve(first), ql::edges().resolve(first)));
  const std::vector<Shape> both{first, second};
  CHECK(in_first.shared_boundary(ql::solids().where(ql::tag("second.solid"))).resolve(ql::Scope(both)).empty());
}

TEST_CASE("an intersection can be refined like any selector") {
  Solid box = tagged_box(1, 1, 1);
  const ql::ShapeSelector top = ql::faces().where(ql::tag("face.top"));
  const ql::ShapeSelector sel = top.boundary("edge").intersection(ql::faces().boundary("edge")).take(2);
  CHECK(sel.resolve(box).size() == 2);
  CHECK(sel.set_operation() == "intersection");
  CHECK(sel.operands().size() == 2);
}

// ---- cardinality failures ----------------------------------------------------------------------------------------
TEST_CASE("a violated exactly() reports what matched and what exists instead") {
  const Solid box = ql_test::box(1, 1, 1);
  try {
    (void)ql::faces().where(ql::prop("geom.type", "==", "PLANE")).take(2).exactly(1).resolve(box);
    FAIL("expected an Error");
  } catch (const Error& e) {
    CHECK(e.operation() == "ql.face.resolve");
    CHECK(e.guidance().what_happened == "QL selector expected exactly 1 face(s), got 2");
    REQUIRE(e.guidance().measurements.size() == 3);
    CHECK(e.guidance().measurements[0].display() == "matched_count: 2");
    CHECK(e.guidance().measurements[1].display() == "candidate_count: 6");
    CHECK(e.guidance().measurements[2].display() == "expected_count: 1");
    CHECK(e.guidance().inventory.size() == 6);  // 2 hits + the 4 other faces as near misses
    CHECK(e.guidance().inventory[0].symbol == "F1");
    CHECK(e.guidance().inventory[0].status == "hit");
    CHECK(e.guidance().inventory[2].status == "near_miss");
    CHECK(e.guidance().repair.size() == 1);
    CHECK(e.guidance().repair[0].find("Tighten the predicate") != std::string::npos);
    CHECK(e.guidance().documentation_hint == "For full usage details, run help(ql.face.resolve).");
    CHECK(std::string(e.what()).find("Inventory:") != std::string::npos);
  }
}

TEST_CASE("at_least and at_most name their mode; zero hits list near misses only") {
  const Solid box = ql_test::box(1, 1, 1);
  const std::string zero = error_text([&] { (void)ql::faces().where(ql::surface_type("SPHERE")).at_least(1).resolve(box); });
  CHECK(zero.find("What happened: QL selector expected at least 1 face(s), got 0") != std::string::npos);
  CHECK(zero.find("[hit]") == std::string::npos);
  CHECK(zero.find("align predicate values") != std::string::npos);
  CHECK(zero.find("Booleans and fillets re-split topology") != std::string::npos);

  const std::string many = error_text([&] { (void)ql::edges().at_most(3).resolve(box); });
  CHECK(many.find("expected at most 3 edge(s), got 12") != std::string::npos);
  CHECK(many.find("E1 [hit] line, length 1 mm") != std::string::npos);
}

TEST_CASE("the near-miss list is capped at eight; hits are always listed") {
  const Solid box = ql_test::box(1, 1, 1);  // 12 edges
  try {
    (void)ql::edges().where(ql::prop("geom.center.z", "<", 0.1)).exactly(1).resolve(box);
    FAIL("expected an Error");
  } catch (const Error& e) {
    int hits = 0, misses = 0;
    for (const auto& entry : e.guidance().inventory) (entry.status == "hit" ? hits : misses)++;
    CHECK(hits == 4);
    CHECK(misses == 8);
  }
}

TEST_CASE("an unresolvable diagnosis degrades to the plain count error") {
  const Solid part = ql_test::split_band_solid();
  // The matched faces come from a traversal, but a list scope's candidates are the solids in it:
  // the logical-group mapping cannot find them, and the failure must still be reported.
  const std::vector<Shape> scope{part};
  const auto query = ql::solids().boundary("face").where(ql::surface_type("CYLINDER")).exactly(1);
  CHECK_THROWS_WITH_AS((void)query.resolve(ql::Scope(scope)), "QL selector expected exactly 1 face(s), got 3", ValueError);
}

// ---- builders and serialization -------------------------------------------------------------------------------------
TEST_CASE("fluent builders do not modify the selector they are called on") {
  const ql::ShapeSelector base = ql::faces();
  const ql::ShapeSelector narrowed = base.where(ql::tag("a")).take(1).exactly(1);
  CHECK_FALSE(base.predicate().has_value());
  CHECK_FALSE(base.limit_count().has_value());
  CHECK(base.cardinality().empty());
  CHECK(narrowed.limit_count() == 1);
  CHECK(narrowed.cardinality().size() == 1);
}

TEST_CASE("where() calls are and-ed in a nested payload, like Python") {
  const ql::ShapeSelector s = ql::faces().where(ql::tag("a")).where(ql::tag("b")).where(ql::tag("c"));
  const Value payload = s.to_value();
  const Value& predicate = *payload.find("predicate");
  CHECK(predicate.find("kind")->as_string() == "and");
  CHECK(predicate.find("children")->as_array()[0].find("kind")->as_string() == "and");
  CHECK(predicate.find("children")->as_array()[1].find("data")->find("pattern")->as_string() == "c");
}

TEST_CASE("the payload of an edge selector, key by key") {
  const ql::ShapeSelector s =
      ql::edges().where(ql::prop("geom.type", "==", "CIRCLE")).order_by(ql::key("geom.center.z")).take(1).exactly(1);
  const Value payload = s.to_value();
  std::vector<std::string> keys;
  for (const auto& [name, item] : payload.as_object()) keys.push_back(name);
  CHECK(keys == std::vector<std::string>{"target_kind", "order_desc", "cardinality", "predicate", "order_key", "order_keys", "limit"});
  CHECK(payload.find("limit")->as_int() == 1);
  CHECK(payload.find("cardinality")->find("exactly")->as_int() == 1);
  CHECK(payload.find("order_keys")->as_array()[0].find("desc")->as_bool() == false);
  CHECK(ql::selector_from_value(payload).to_value() == payload);
}

TEST_CASE("graph source, several keys and range cardinality round-trip") {
  const ql::ShapeSelector s = ql::faces()
                                  .from_source("node_a", 0)
                                  .order_by(ql::key("geom.center.z"), true)
                                  .order_by(ql::key("geom.center.x"))
                                  .at_least(1)
                                  .at_most(6);
  const Value payload = s.to_value();
  CHECK(payload.find("source_node_id")->as_string() == "node_a");
  CHECK(payload.find("source_output_slot")->as_int() == 0);
  CHECK(payload.find("order_keys")->size() == 2);
  CHECK(payload.find("cardinality")->find("at_least")->as_int() == 1);
  CHECK(payload.find("cardinality")->find("at_most")->as_int() == 6);
  CHECK(ql::selector_from_value(payload).to_value() == payload);

  // a traversal inherits the anchor of the selector it grows from
  const ql::ShapeSelector walk = s.boundary("edge");
  CHECK(walk.source_node_id() == "node_a");
  CHECK(walk.to_value().find("source")->find("source_node_id")->as_string() == "node_a");
}

TEST_CASE("set operations and incident faces round-trip") {
  const ql::ShapeSelector a = ql::faces().where(ql::tag("x"));
  const ql::ShapeSelector b = ql::faces().where(ql::tag("y"));
  const ql::ShapeSelector s = ql::edges().incident_to({a, b}, true).incident_face_count(2);
  CHECK(ql::selector_from_value(s.to_value()).to_value() == s.to_value());
  const ql::ShapeSelector shared = a.shared_boundary(b);
  const Value payload = shared.to_value();
  CHECK(payload.find("set_operation")->find("op")->as_string() == "intersection");
  CHECK(payload.find("set_operation")->find("operands")->size() == 2);
  CHECK(ql::selector_from_value(payload) == shared);
}

TEST_CASE("builder arguments are validated with the Python messages") {
  const ql::ShapeSelector f = ql::faces();
  CHECK_THROWS_WITH_AS((void)f.take(-1), "count must be >= 0", ValueError);
  CHECK_THROWS_WITH_AS((void)f.exactly(-1), "count must be >= 0", ValueError);
  CHECK_THROWS_WITH_AS((void)f.from_source("", 0), "node_id must be a non-empty string", ValueError);
  CHECK_THROWS_WITH_AS((void)f.from_source("n", -1), "output_slot must be >= 0", ValueError);
  CHECK_THROWS_WITH_AS((void)f.traverse("adjacent", "edge"), "unsupported traversal relation: adjacent", ValueError);
  CHECK_THROWS_WITH_AS((void)f.boundary("shell"), "unsupported traversal target kind: shell", ValueError);
  CHECK_THROWS_WITH_AS((void)f.intersection(ql::edges()), "intersection operands must select the same topology kind", ValueError);
  CHECK_THROWS_WITH_AS((void)f.incident_to({f}), "incident_to is only valid on an Edge selector", ValueError);
  CHECK_THROWS_WITH_AS((void)ql::edges().incident_to({}), "incident_to requires one or more Face selectors", TypeError);
  CHECK_THROWS_WITH_AS((void)ql::edges().incident_to({ql::edges()}), "incident_to requires one or more Face selectors", TypeError);
  CHECK_THROWS_WITH_AS((void)f.incident_face_count(2), "incident_face_count is only valid on an Edge selector", ValueError);
  CHECK_THROWS_WITH_AS((void)ql::edges().incident_face_count(-1), "incident face count must be >= 0", ValueError);
  CHECK(f.boundary(" EDGE ").target_kind() == "edge");
  CHECK(f.traverse(" Boundary ", "wire").traversal()->relation == "boundary");
}

TEST_CASE("from_value rejects malformed selector payloads") {
  const auto payload = [](const char* kind) {
    Value v = Value::object();
    v.set("target_kind", kind);
    return v;
  };
  CHECK_THROWS_AS((void)ql::selector_from_value(Value::object()), Exception);  // KeyError: 'target_kind'
  Value bad_set = payload("face");
  bad_set.set("set_operation", Value(1));
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(bad_set), "selector set_operation must be an object", ValueError);
  Value fields = Value::object();
  fields.set("op", "intersection");
  bad_set.set("set_operation", fields);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(bad_set), "selector set_operation has invalid fields", ValueError);
  fields.set("operands", Value::array());
  bad_set.set("set_operation", fields);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(bad_set), "selector intersection requires at least two operands", ValueError);
  fields.set("op", "union");
  bad_set.set("set_operation", fields);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(bad_set), "unsupported selector set operation: union", ValueError);

  Value mismatch = payload("face");
  Value set = Value::object();
  set.set("op", "intersection");
  set.set("operands", Value(Value::Array{payload("face"), payload("edge")}));
  mismatch.set("set_operation", set);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(mismatch), "selector intersection operands must match target_kind", ValueError);

  Value incident = payload("face");
  Value inc = Value::object();
  inc.set("selectors", Value(Value::Array{payload("face")}));
  inc.set("distinct", true);
  incident.set("incident_faces", inc);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(incident), "incident_faces is only valid for edge selectors", ValueError);
  Value wrong_kind = payload("edge");
  inc.set("selectors", Value(Value::Array{payload("edge")}));
  wrong_kind.set("incident_faces", inc);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(wrong_kind), "incident_faces selectors must select faces", ValueError);

  Value card = payload("edge");
  Value both = Value::object();
  both.set("exactly", 2);
  both.set("at_least", 1);
  card.set("incident_face_cardinality", both);
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(card), "incident_face_cardinality only supports exactly", ValueError);

  Value keys = payload("face");
  keys.set("order_keys", Value(Value::Array{Value(1)}));
  CHECK_THROWS_WITH_AS((void)ql::selector_from_value(keys), "selector order_keys entries must contain a key object", ValueError);
}

TEST_CASE("an unknown target kind is carried along and fails when resolved") {
  const ql::ShapeSelector odd("widget");
  CHECK(odd.to_value().find("target_kind")->as_string() == "widget");
  CHECK_THROWS_WITH_AS((void)odd.resolve(ql_test::box(1, 1, 1)), "cannot resolve QL selector scope for target_kind=widget", TypeError);
}

// ---- the semantic seam ----------------------------------------------------------------------------------------------------
TEST_CASE("a ql selector is a semantic ShapeSelector: resolve, serialize, anchor") {
  const Solid box = tagged_box(1, 1, 1);
  const ql::ShapeSelector top = ql::faces().where(ql::tag("face.top")).exactly(1);
  const SelectorPtr seam = top.shared();
  CHECK(seam->resolve(box).size() == 1);
  CHECK(seam->to_value() == top.to_value());
  CHECK_FALSE(seam->source().has_value());

  const SelectorPtr anchored = seam->from_source({"node_7", 2});
  REQUIRE(anchored);
  REQUIRE(anchored->source().has_value());
  CHECK(anchored->source()->node_id == "node_7");
  CHECK(anchored->source()->output_slot == 2);
  CHECK(anchored->to_value().find("source_node_id")->as_string() == "node_7");
  CHECK(anchored->resolve(box).size() == 1);
}

namespace {
class SelectionLog final : public Recorder {
 public:
  void record(const OpRecord&, const std::vector<Shape>&) override {}
  void record_selection(const Shape& source, const std::vector<Shape>& picked, const std::string& kind) override {
    sources.push_back(source);
    counts.push_back(picked.size());
    kinds.push_back(kind);
  }
  std::vector<Shape> sources;
  std::vector<std::size_t> counts;
  std::vector<std::string> kinds;
};
}  // namespace

TEST_CASE("resolve_recorded reports the pick to the active recorder; resolve does not") {
  const Solid box = tagged_box(1, 1, 1);
  SelectionLog log;
  const RecorderScope scope(&log);
  (void)ql::faces().resolve(box);
  CHECK(log.counts.empty());
  const auto picked = ql::faces().where(ql::tag("face.top")).resolve_recorded(box);
  CHECK(picked.size() == 1);
  REQUIRE(log.counts.size() == 1);
  CHECK(log.counts[0] == 1);
  CHECK(log.kinds[0] == "face");
  CHECK(log.sources[0].same_entity(box));
  (void)ql::faces().where(ql::tag("no.such.tag")).resolve_recorded(box);
  CHECK(log.counts.size() == 1);  // nothing picked, nothing recorded
}

// ---- resolvers participate ------------------------------------------------------------------------------------------------
TEST_CASE("a registered property resolver extends predicates and keys") {
  const Solid box = ql_test::box(1, 2, 3);
  ql::register_property_resolver("score.", [](const Shape& s, std::string_view path) -> std::optional<Value> {
    if (path == "score.size") return Value(s.kind() == Kind::Face ? 2.0 : 1.0);
    return std::nullopt;
  });
  CHECK(ql::faces().where(ql::prop("score.size", "==", 2)).resolve(box).size() == 6);
  CHECK(ql::edges().where(ql::prop("score.size", "==", 2)).resolve(box).empty());
  CHECK(ql::key("score.size")(box.faces().front()).as_double() == 2.0);
  ql::unregister_property_resolver("score.");
  CHECK(ql::faces().where(ql::prop("score.size", "==", 2)).resolve(box).empty());
}

// ---- scale -----------------------------------------------------------------------------------------------------------------------
TEST_CASE("selecting from a model with thousands of faces") {
  std::vector<Solid> boxes;
  for (int i = 0; i < 400; ++i) boxes.push_back(ql_test::box(1, 1, 1, {3.0 * i, 0, 0}));
  const Compound model = ql_test::compound_of(boxes);
  const auto up = ql::faces().where(ql::and_({ql::surface_type("PLANE"), ql::prop("geom.normal.z", ">", 0.9)})).resolve(model);
  CHECK(up.size() == 400);
  const auto last = ql::solids().order_by(ql::key("geom.bbox.max.x"), true).take(1).exactly(1).resolve(model);
  REQUIRE(last.size() == 1);
  CHECK(last[0].bounding_box().xmax == doctest::Approx(3.0 * 399 + 1));
}
