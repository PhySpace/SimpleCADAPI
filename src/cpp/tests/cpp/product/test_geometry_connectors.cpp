// Connectors anchored to faces, edges and vertices of a body.
#include "support.hpp"

using namespace scad::product_test;

namespace {

Face top_face(const Solid& box) {
  for (const Face& face : box.faces()) {
    if (face.normal_at().z > 0.99) return face;
  }
  FAIL("no top face");
  return box.faces().front();
}

}  // namespace

TEST_CASE("a face connector sits at the face centre with z along the normal") {
  const Solid box = make_box_rsolid(2.0, 4.0, 6.0);
  const Connector connector = make_face_connector_rconnector("top", top_face(box));
  const Placement frame = connector.placement();
  check_vec(frame.origin(), {0, 0, 6});
  check_vec(frame.z_axis(), {0, 0, 1});

  const Connector flipped = make_face_connector_rconnector("top_flipped", top_face(box), std::nullopt, true);
  check_vec(flipped.placement().z_axis(), {0, 0, -1});
  CHECK(connector.geometry_ref()->kind() == "face");
  CHECK(connector.geometry_ref()->geo_selector().find("geom_type")->as_string() == "PLANE");
  CHECK(connector.geometry_ref()->geo_selector().find("mode")->as_string() == "geo_exact");
  CHECK(connector.anchor_kind() == "geometry");
}

TEST_CASE("an edge connector sits at the midpoint with z along the edge") {
  const Solid box = make_box_rsolid(2.0, 4.0, 6.0);
  for (const Edge& edge : box.edges()) {
    const Vec3 start = edge.start_vertex().coordinates();
    const Vec3 end = edge.end_vertex().coordinates();
    if (std::abs(start.x - end.x) < 1e-9 && std::abs(start.y - end.y) < 1e-9) {
      const Connector connector = make_edge_connector_rconnector("rail", edge);
      const Placement frame = connector.placement();
      CHECK(std::abs(frame.z_axis().z) == doctest::Approx(1.0));
      CHECK(frame.origin().z == doctest::Approx(3.0));
      CHECK(connector.geometry_ref()->geo_selector().find("geom_type")->as_string() == "LINE");
      return;
    }
  }
  FAIL("no vertical edge");
}

TEST_CASE("a vertex connector has the identity axes") {
  const Solid box = make_box_rsolid(2.0, 4.0, 6.0);
  const Vertex vertex = box.edges().front().start_vertex();
  const Connector connector = make_vertex_connector_rconnector("corner", vertex, "Corner", true);
  const Placement frame = connector.placement();
  check_vec(frame.origin(), vertex.coordinates());
  check_vec(frame.x_axis(), {1, 0, 0});
  check_vec(frame.z_axis(), {0, 0, 1});
  CHECK(*connector.name() == "Corner");
}

TEST_CASE("a connector operator reports its own guidance when it fails") {
  const Solid box = make_box_rsolid(1.0, 1.0, 1.0);
  const auto error = failure_of([&] { make_face_connector_rconnector("bad id", top_face(box)); });
  REQUIRE(error);
  CHECK(error->operation() == "make_face_connector_rconnector");
  CHECK(error->guidance().what_happened == "Failed to create the face connector.");
  CHECK(error->guidance().technical_details.find("connector_id must start with a letter") != std::string::npos);
}
