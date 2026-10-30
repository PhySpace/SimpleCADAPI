#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>

#include "scad/core/error.hpp"
#include "scad/topo/shape.hpp"

using namespace scad;

namespace {
Solid make_box(double x, double y, double z) {
  return Solid(BRepPrimAPI_MakeBox(x, y, z).Solid());
}
}  // namespace

TEST_CASE("a box enumerates 6 faces, 12 unique edges, 24 edge occurrences") {
  const Solid box = make_box(10, 20, 30);
  CHECK(box.volume() == doctest::Approx(6000.0));
  CHECK(box.faces().size() == 6);
  CHECK(box.edges().size() == 12);
  CHECK(box.edge_occurrences().size() == 24);
}

TEST_CASE("faces of one root share semantic state across enumerations") {
  const Solid box = make_box(1, 1, 1);
  Face first = box.faces()[0];
  first.add_tag("role.mount");
  const Face again = box.faces()[0];
  CHECK(again.has_tag("role.mount"));
  CHECK(again.same_entity(first));
  CHECK_FALSE(box.faces()[1].has_tag("role.mount"));
}

TEST_CASE("a face's outer wire is tagged and inner wires are found") {
  const Solid box = make_box(1, 1, 1);
  const Face face = box.faces()[0];
  CHECK(face.outer_wire().has_tag("wire.outer", TagScope::Local));
  CHECK(face.inner_wires().empty());
  for (const Edge& e : face.edges())
    CHECK(e.has_tag("edge.boundary", TagScope::Local));
}

TEST_CASE("downward tags are inherited by sub-shapes reached through the parent") {
  Solid box = make_box(1, 1, 1);
  Face face = box.faces()[0];
  box.apply_tag("group.all", /*propagate=*/true);
  CHECK(face.has_tag("group.all", TagScope::Inherited));
  CHECK_FALSE(face.has_tag("group.all", TagScope::Local));
  CHECK(face.has_tag("group.all", TagScope::Effective));
}

TEST_CASE("asking an edge for its incident faces does not hand the face's downward tags to the other faces") {
  Solid box = make_box(1, 1, 1);
  std::vector<Face> faces = box.faces();
  faces[0].apply_tag("group.first", /*propagate=*/true);
  for (const Edge& edge : faces[0].edges())
    for (const Face& incident : edge.incident_faces())
      (void)incident;  // the faces contain the edge; they are not its children
  int tagged = 0;
  for (const Face& face : box.faces())
    if (face.has_tag("group.first"))
      ++tagged;
  CHECK(tagged == 1);
  for (const Vertex& vertex : box.edges()[0].vertices())
    for (const Edge& edge : vertex.incident_edges())
      CHECK_FALSE(edge.has_tag("group.first", TagScope::Local));
}

TEST_CASE("faces report orientation-correct outward normals") {
  const Solid box = make_box(2, 2, 2);
  int up = 0, down = 0;
  for (const Face& f : box.faces()) {
    const Vec3 n = f.normal_at();
    if (n.z > 0.9)
      ++up;
    if (n.z < -0.9)
      ++down;
  }
  CHECK(up == 1);
  CHECK(down == 1);
}

TEST_CASE("auto_tag_faces names the faces of a box") {
  Solid box = make_box(2, 3, 4);
  box.auto_tag_faces("box");
  int tagged = 0;
  for (const char* name : {"face.top", "face.bottom", "face.front", "face.back", "face.left", "face.right"}) {
    int hits = 0;
    for (const Face& f : box.faces())
      hits += f.has_tag(name, TagScope::Local) ? 1 : 0;
    CHECK(hits == 1);
    tagged += hits;
  }
  CHECK(tagged == 6);
}

TEST_CASE("typed constructors reject the wrong kind") {
  const Solid box = make_box(1, 1, 1);
  CHECK_THROWS_AS((void)Face{static_cast<const Shape&>(box)}, TypeError);
  CHECK_THROWS_AS((void)Face(box.wrapped()), TypeError);
}

TEST_CASE("a cylinder auto-tags bottom, top and side") {
  Solid cyl(BRepPrimAPI_MakeCylinder(5.0, 10.0).Solid());
  cyl.auto_tag_faces("cylinder");
  int side = 0, top = 0, bottom = 0;
  for (const Face& f : cyl.faces()) {
    side += f.has_tag("face.side", TagScope::Local);
    top += f.has_tag("face.top", TagScope::Local);
    bottom += f.has_tag("face.bottom", TagScope::Local);
  }
  CHECK(side == 1);
  CHECK(top == 1);
  CHECK(bottom == 1);
}
