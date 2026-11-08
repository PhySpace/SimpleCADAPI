// ql::ref: a reference record as a predicate, resolved by the installed resolver in the selector's scope.
#include <string>

#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/ql.hpp"

using namespace scad;
using namespace scad::ql;

namespace {

Value record_of(const std::string& role) {
  Value record = Value::object();
  record.set("kind", "face");
  record.set("role", role);
  return record;
}

// Installs `resolver` for one test case and removes it after.
struct Installed {
  explicit Installed(ReferenceResolver resolver) { set_reference_resolver(std::move(resolver)); }
  ~Installed() { set_reference_resolver({}); }
  Installed(const Installed&) = delete;
  Installed& operator=(const Installed&) = delete;
};

}  // namespace

TEST_CASE("a reference predicate is data: it round-trips and compares by its record") {
  const Predicate predicate = ref(record_of("box.top"));
  CHECK(predicate.kind() == "ref");
  CHECK(Predicate::from_value(predicate.to_value()) == predicate);
  CHECK_FALSE(ref(record_of("box.bottom")) == predicate);
  CHECK_THROWS_AS(ref(Value("box.top")), ValueError);
  Value bad = Value::object();
  bad.set("ref", Value("box.top"));
  CHECK_THROWS_AS(Predicate("ref", bad), ValueError);
}

TEST_CASE("the resolver answers once per reference per run, in the selector's scope") {
  const Solid box = ql_test::box(4, 2, 1);
  int calls = 0;
  const Installed installed([&](const Shape& scope, const Value& record) {
    ++calls;
    CHECK(scope.same_entity(box));
    CHECK(record.find("role")->as_string() == "top");
    std::vector<Shape> out;
    for (const Face& face : Solid(scope).faces())
      if (face.center().z > 0.99)
        out.push_back(face);
    return out;
  });
  const std::vector<Shape> found = faces().where(ref(record_of("top"))).resolve(box);
  REQUIRE(found.size() == 1);
  CHECK(found.front().center().z == doctest::Approx(1.0));
  CHECK(calls == 1);  // six candidates, one resolution
  CHECK(faces().where(or_({ref(record_of("top")), ref(record_of("top"))})).resolve(box).size() == 1);
  CHECK(calls == 2);  // the same record twice in one run: still one resolution
}

TEST_CASE("a reference needs one shape to resolve in, and a resolver") {
  const Solid box = ql_test::box(1, 1, 1);
  CHECK_THROWS_AS((void)ref(record_of("top")).matches(box.faces().front()), ValueError);
  CHECK_THROWS_AS((void)faces().where(ref(record_of("top"))).resolve(box), ValueError);  // no resolver installed
  const Installed installed([](const Shape&, const Value&) { return std::vector<Shape>{}; });
  CHECK_THROWS_AS((void)faces().where(ref(record_of("top"))).resolve(Scope(std::vector<Shape>{box})), ValueError);
}

TEST_CASE("what the resolver throws (a split or lost reference) leaves the query as it is") {
  const Solid box = ql_test::box(1, 1, 1);
  const Installed installed([](const Shape&, const Value&) -> std::vector<Shape> {
    throw MessageError("", "ElementRefError: the referenced entity was split into 2 pieces: choose one");
  });
  CHECK_THROWS_WITH_AS((void)faces().where(ref(record_of("top"))).resolve(box),
                       doctest::Contains("split into 2 pieces"), Error);
}
