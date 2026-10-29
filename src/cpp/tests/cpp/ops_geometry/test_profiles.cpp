// Circles, ellipses, rectangles, faces from wires, the open-wire diagnosis.
#include "support.hpp"

using namespace scad;
using namespace scad::geometry_test;

TEST_CASE("circles as edge, wire and face") {
  const Scalar3 centre = scalar3(1, 2, 3);
  const Edge edge = make_circle_redge(centre, 2.0, scalar3(0, 0, 1), "rim");
  CHECK(edge.length() == doctest::Approx(4 * kPi));
  CHECK(has_tag(edge, "rim.edge"));

  const Wire wire = make_circle_rwire(centre, 2.0, scalar3(0, 0, 1), {.tag_prefix = "hole", .edge_tag = "outer"});
  CHECK(wire.is_closed());
  CHECK(has_tag(wire, "hole.wire"));
  CHECK(count_with_tag(wire.edges(), "hole.edge.outer") == 1);
  // An edge tag alone names the edge without a prefix.
  CHECK(count_with_tag(make_circle_rwire(centre, 2.0, scalar3(0, 0, 1), {.edge_tag = "outer"}).edges(), "outer") == 1);

  const Face face = make_circle_rface(centre, 2.0, scalar3(0, 1, 0), {.tag_prefix = "disc"});
  CHECK(face.area() == doctest::Approx(4 * kPi));
  CHECK(has_tag(face, "disc.face"));
  check_box(face, {-1, 2, 1}, {3, 2, 5}, 1e-6);

  CHECK(failure_of([] { make_circle_redge(scalar3(0, 0, 0), -1.0); })->operation() == "make_circle_redge");
  // The wire and face makers report the edge's failure, as Python does.
  CHECK(failure_of([] { make_circle_rwire(scalar3(0, 0, 0), 0); })->operation() == "make_circle_redge");
}

TEST_CASE("ellipses") {
  const Wire wire =
      make_ellipse_rwire(scalar3(0, 0, 0), 3.0, 1.0, scalar3(0, 0, 1), {.tag_prefix = "slot", .edge_tag = "outline"});
  CHECK(wire.is_closed());
  CHECK(count_with_tag(wire.edges(), "slot.edge.outline") == 1);
  CHECK(make_ellipse_rface(scalar3(0, 0, 0), 3.0, 1.0).area() == doctest::Approx(3 * kPi));
  const Face turned =
      make_ellipse_rface(scalar3(0, 0, 0), 3.0, 1.0, scalar3(0, 0, 1), {.major_direction = scalar3(0, 1, 0)});
  check_box(turned, {-1, -3, 0}, {1, 3, 0}, 1e-6);

  CHECK(failure_of([] { make_ellipse_redge(scalar3(0, 0, 0), -3.0, 1.0); })->operation() == "make_ellipse_redge");
  const auto larger_minor = failure_of([] { make_ellipse_redge(scalar3(0, 0, 0), 1.0, 3.0); });
  REQUIRE(larger_minor);
  CHECK(larger_minor->guidance().possible_causes[1] == "The minor radius exceeds the major radius.");
}

TEST_CASE("rectangles span their width along the plane's x axis") {
  const Wire wire = make_rectangle_rwire(30.0, 10.0);
  check_box(wire, {-15, -5, 0}, {15, 5, 0});
  CHECK(wire.edges().size() == 4);
  const Face face = make_rectangle_rface(2, 1, scalar3(1, 0, 0), scalar3(0, 1, 0), {.tag_prefix = "plate"});
  CHECK(face.area() == doctest::Approx(2.0));
  // For a +Y normal the plane's x axis is the global Z and its y axis is X.
  check_box(face, {0.5, 0, -1}, {1.5, 0, 1}, 1e-6);

  const Wire named =
      make_rectangle_rwire(2, 1, scalar3(0, 0, 0), scalar3(0, 0, 1),
                           {.tag_prefix = "frame", .edge_tags = std::vector<std::string>{"a", "b", "c", "d"}});
  CHECK(count_with_tag(named.edges(), "frame.edge.c") == 1);
  CHECK(has_tag(named, "frame.wire"));
  CHECK(count_with_tag(make_rectangle_rwire(2, 1).edges(), "frame.edge.line1") == 0);
  CHECK(count_with_tag(make_rectangle_rwire(2, 1, scalar3(0, 0, 0), scalar3(0, 0, 1), {.tag_prefix = "f"}).edges(),
                       "f.edge.line1") == 1);

  CHECK(failure_of([] { make_rectangle_rwire(0, 1); })->operation() == "make_rectangle_rwire");
  CHECK(failure_of([] { make_rectangle_rwire(1, 1, scalar3(0, 0, 0), scalar3(0, 0, 0)); })->operation() ==
        "make_rectangle_rwire");
  const auto wrong_count = failure_of([] {
    make_rectangle_rwire(1, 1, scalar3(0, 0, 0), scalar3(0, 0, 1), {.edge_tags = std::vector<std::string>{"a", "b"}});
  });
  REQUIRE(wrong_count);
  CHECK(wrong_count->guidance().technical_details == "ValueError: edge_tags must contain exactly 4 tags, got 2");
}

TEST_CASE("make_face_from_wire_rface keeps the wire's names") {
  const Wire rect = make_rectangle_rwire(2, 1, scalar3(0, 0, 0), scalar3(0, 0, 1), {.tag_prefix = "frame"});
  const Face face = make_face_from_wire_rface(rect, scalar3(0, 0, 1), "plate");
  CHECK(face.area() == doctest::Approx(2.0));
  CHECK(has_tag(face, "plate.face"));
  CHECK(count_with_tag(face.edges(), "frame.edge.line1") == 1);

  const Edge edge = make_line_redge(scalar3(0, 0, 0), scalar3(1, 0, 0));
  const auto not_wire = failure_of([&] { make_face_from_wire_rface(edge); });
  REQUIRE(not_wire);
  CHECK(not_wire->guidance().possible_causes.front() == "The input is not a Wire instance.");
}

TEST_CASE("an open wire is diagnosed with the measured gap") {
  const Wire open = make_polyline_rwire({scalar3(0, 0, 0), scalar3(2, 0, 0), scalar3(2, 2, 0)});
  const std::optional<WireGapDiagnosis> diagnosis = diagnose_open_wire(open);
  REQUIRE(diagnosis);
  CHECK(diagnosis->gap_distance == doctest::Approx(std::sqrt(8.0)));
  CHECK(diagnosis->edge_count == 2);
  CHECK(diagnosis->chain_count == 1);
  CHECK(diagnosis->dangling_count == 2);

  const auto error = failure_of([&] { make_face_from_wire_rface(open); });
  REQUIRE(error);
  CHECK(error->guidance().what_happened ==
        "the given wire is not closed, so it cannot be used to create a face; measured gap 2.828 mm");
  CHECK(error->guidance().measurements.size() == 4);
  CHECK(error->guidance().repair.front().find("add a segment (or arc) across the two ends") != std::string::npos);

  const Wire pieces = make_wire_from_edges_rwire({make_line_redge(scalar3(0, 0, 0), scalar3(1, 0, 0))});
  CHECK(diagnose_open_wire(pieces)->gap_distance == doctest::Approx(1.0));  // a lone segment: its own two ends
}

TEST_CASE("make_face_from_wires_rface punches holes") {
  const Wire outer = make_circle_rwire(scalar3(0, 0, 0), 2.0);
  const Wire inner = make_circle_rwire(scalar3(0, 0, 0), 1.0);
  const Face ring = make_face_from_wires_rface(outer, {inner});
  CHECK(ring.area() == doctest::Approx(3 * kPi));
  CHECK(ring.wires().size() == 2);

  const Wire square = make_rectangle_rwire(10, 10);
  const Face plate = make_face_from_wires_rface(
      square, {make_circle_rwire(scalar3(-2, 0, 0), 1.0), make_circle_rwire(scalar3(2, 0, 0), 1.0)});
  CHECK(plate.area() == doctest::Approx(100 - 2 * kPi));

  const Edge edge = make_line_redge(scalar3(0, 0, 0), scalar3(1, 0, 0));
  CHECK(failure_of([&] { make_face_from_wires_rface(edge, {inner}); })->operation() == "make_face_from_wires_rface");
  CHECK(failure_of([&] { make_face_from_wires_rface(outer, {edge}); })->guidance().technical_details ==
        "ValueError: inner_wires must contain only Wire objects");
  CHECK(
      failure_of([&] { make_face_from_wires_rface(outer, {inner}, scalar3(0, 0, 0)); })->guidance().technical_details ==
      "ValueError: normal must be a non-zero finite vector");
}
