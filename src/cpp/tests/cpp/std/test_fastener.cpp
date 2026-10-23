// Bolts, nuts, and the standard-size tables.  The numbers are the Python SDK's.
#include "fixtures.hpp"

using namespace scad;
using namespace scad::std_test;
using doctest::Approx;

TEST_CASE("catalog lookups: coarse pitch, hex head, minor diameter") {
  CHECK(*stdlib::metric_coarse_pitch(10.0) == Approx(1.5));
  CHECK(*stdlib::metric_coarse_pitch(10.0 + 5e-10) == Approx(1.5));
  CHECK_FALSE(stdlib::metric_coarse_pitch(9.0).has_value());
  const auto head = stdlib::metric_hex_head_dimensions(12.0);
  REQUIRE(head.has_value());
  CHECK(head->width == Approx(18.0));
  CHECK(head->height == Approx(7.5));
  CHECK_FALSE(stdlib::metric_hex_head_dimensions(2.0).has_value());

  const auto [pitch_diameter, minor] = stdlib::metric_thread_dimensions(10.0, 1.5);
  CHECK(pitch_diameter == Approx(10.0 - 0.6495 * 1.5));
  CHECK(minor == Approx(10.0 - 1.0825 * 1.5));
  CHECK(stdlib::standard_partial_thread_length(8.0, 24.0) == Approx(22.0));
  CHECK(stdlib::standard_partial_thread_length(8.0, 150.0) == Approx(28.0));
  CHECK(stdlib::standard_partial_thread_length(8.0, 300.0) == Approx(41.0));

  CHECK(stdlib::resolve_thread_pitch(9.0, 1.25).source == "explicit");
  CHECK(failure_message([] { (void)stdlib::resolve_thread_pitch(9.0, std::nullopt); }) ==
        "thread_pitch is required when diameter is outside the metric coarse series");
  CHECK(failure_message([] { (void)stdlib::choice("head_style", "wing", {"button", "hex"}); }) ==
        "head_style must be one of: button, hex");
  CHECK(stdlib::choice("head_style", "HEX", {"button", "hex"}) == "hex");
}

TEST_CASE("bolt with a modeled thread: default hex bolt") {
  const Solid bolt = make_bolt_rsolid(8.0, 24.0);
  CHECK(bolt.volume() == Approx(1758.7579781162303).epsilon(1e-6));
  CHECK(bolt.faces().size() == 54);
  CHECK(bolt.edges().size() == 116);
  CHECK(has_tag(bolt, "role.fastener.bolt"));
  CHECK(has_tag(bolt, "group.fasteners"));
  const Value meta = bolt.get_metadata("std.fastener.bolt");
  CHECK(meta.find("thread_style")->as_string() == "full");
  CHECK(meta.find("requested_thread_style")->as_string() == "auto");
  CHECK(number(meta, "thread_length") == Approx(24.0));
  CHECK(number(meta, "thread_phase_degrees") == Approx(0.0));
}

TEST_CASE("bolt: metric coarse series and the standard partial thread") {
  BoltOptions options;
  options.thread_detail = "cosmetic";
  const Solid bolt = make_bolt_rsolid(10.0, 40.0, options);
  const Value meta = bolt.get_metadata("std.fastener.bolt");
  CHECK(number(meta, "thread_pitch") == Approx(1.5));
  CHECK(meta.find("thread_pitch_source")->as_string() == "metric_coarse");
  CHECK(meta.find("thread_style")->as_string() == "partial");
  CHECK(number(meta, "thread_start") == Approx(14.0));
  CHECK(number(meta, "thread_length") == Approx(26.0));
  CHECK(number(meta, "head_width") == Approx(16.0));
  CHECK(number(meta, "head_height") == Approx(6.4));
  CHECK(number(meta, "head_across_corners") == Approx(16.0 / 0.8660254038));
  CHECK(number(meta, "underhead_fillet_radius") == Approx(0.6));
  CHECK(number(meta, "recommended_mating_hole_chamfer_min") == Approx(0.6));
  CHECK(number(meta, "pitch_diameter") == Approx(10.0 - 0.6495 * 1.5));
}

TEST_CASE("bolt: auto becomes full when the standard partial length is not shorter than the bolt") {
  BoltOptions options;
  options.thread_detail = "cosmetic";
  const Value meta = make_bolt_rsolid(4.0, 13.0, options).get_metadata("std.fastener.bolt");
  CHECK(meta.find("requested_thread_style")->as_string() == "auto");
  CHECK(meta.find("thread_style")->as_string() == "full");
  CHECK(number(meta, "thread_length") == Approx(13.0));
}

TEST_CASE("bolt: every head and drive style builds") {
  struct Style {
    const char* head;
    const char* drive;
    double volume;
    std::size_t faces;
  };
  const Style styles[] = {{"countersunk", "slot", 1751.9050664697668, 0},
                          {"cylindrical", "hex_socket", 2064.1553991428723, 0},
                          {"square", "none", 2014.0475575624994, 9}};
  for (const Style& style : styles) {
    BoltOptions options;
    options.head_style = style.head;
    options.drive_style = style.drive;
    options.thread_detail = "cosmetic";
    options.thread_style = std::string(style.head) == "countersunk" ? "none" : "auto";
    if (std::string(style.head) == "square") options.thread_style = "partial";
    const Solid bolt = make_bolt_rsolid(8.0, 24.0, options);
    CHECK_MESSAGE(bolt.volume() == Approx(style.volume).epsilon(1e-6), style.head);
  }
}

TEST_CASE("bolt: modeled partial thread with a cross drive and button head") {
  BoltOptions options;
  options.head_style = "button";
  options.thread_style = "partial";
  options.thread_pitch = 1.25;
  options.thread_depth = 0.65;
  options.thread_length = 18.0;
  options.drive_style = "cross";
  const Solid bolt = make_bolt_rsolid(8.0, 24.0, options);
  CHECK(bolt.volume() == Approx(1568.70014208786).epsilon(1e-6));
  CHECK(bolt.faces().size() == 42);
}

TEST_CASE("bolt: an unstable thread phase is skipped, only the chosen one is kept") {
  BoltOptions options;
  options.thread_style = "full";
  options.thread_pitch = 1.0;
  options.thread_depth = 0.45;
  const Solid bolt = make_bolt_rsolid(6.0, 18.0, options);
  CHECK(bolt.volume() == Approx(761.3176983340269).epsilon(1e-6));
  CHECK(number(bolt.get_metadata("std.fastener.bolt"), "thread_phase_degrees") == Approx(45.0));
}

TEST_CASE("bolt: invalid arguments are ValueErrors with the Python text") {
  const auto message = [](double d, double l, BoltOptions o = {}) {
    return failure_message([&] { (void)make_bolt_rsolid(d, l, o); });
  };
  CHECK(message(0.0, 24.0) == "diameter must be positive and finite");
  CHECK(message(9.0, 24.0) == "thread_pitch is required when diameter is outside the metric coarse series");
  BoltOptions wing;
  wing.head_style = "wing";
  CHECK(message(8.0, 24.0, wing) == "head_style must be one of: button, countersunk, cylindrical, hex, square");
  BoltOptions narrow;
  narrow.head_width = 7.0;
  CHECK(message(8.0, 24.0, narrow) == "head_width must be greater than diameter");
  BoltOptions too_long;
  too_long.thread_style = "partial";
  too_long.thread_length = 24.0;
  CHECK(message(8.0, 24.0, too_long) == "partial thread_length must be smaller than length");
  BoltOptions full_with_length;
  full_with_length.thread_style = "full";
  full_with_length.thread_length = 12.0;
  CHECK(message(8.0, 24.0, full_with_length) == "thread_length is only valid when thread_style='partial'");
  BoltOptions stray_drive;
  stray_drive.drive_size = 4.0;
  CHECK(message(8.0, 24.0, stray_drive) == "drive_size and drive_depth require a non-'none' drive_style");
  BoltOptions auto_length;
  auto_length.thread_length = 5.0;
  CHECK(message(8.0, 24.0, auto_length) == "thread_length requires thread_style='partial'");
  BoltOptions big_fillet;
  big_fillet.underhead_fillet_radius = 5.0;
  CHECK(message(8.0, 24.0, big_fillet) == "underhead_fillet_radius is too large for the shank and head dimensions");
}

TEST_CASE("nut: default hex nut with a modeled internal thread") {
  const Solid nut = make_nut_rsolid(8.0, 13.0, 6.5);
  CHECK(nut.volume() == Approx(667.9465078218597).epsilon(1e-6));
  CHECK(nut.faces().size() == 18);
  CHECK(has_tag(nut, "role.fastener.nut"));
  CHECK(has_tag(nut, "group.fasteners"));
  CHECK(number(nut.get_metadata("std.fastener.nut"), "thread_phase_degrees") == Approx(15.0));
}

TEST_CASE("nut: styles, blind holes and the trapezoidal knurled nut") {
  NutOptions blind;
  blind.hole_style = "blind";
  blind.hole_depth = 5.0;
  blind.thread_detail = "cosmetic";
  const Solid blind_nut = make_nut_rsolid(8.0, 13.0, 7.0, blind);
  CHECK(blind_nut.volume() == Approx(773.1806403898079).epsilon(1e-6));
  NutOptions through;
  through.thread_detail = "cosmetic";
  CHECK(blind_nut.volume() > make_nut_rsolid(8.0, 13.0, 7.0, through).volume());

  NutOptions knurled;
  knurled.nut_style = "knurled";
  knurled.hole_style = "blind";
  knurled.hole_depth = 5.5;
  knurled.thread_form = "trapezoidal";
  knurled.thread_pitch = 1.25;
  knurled.thread_depth = 0.65;
  knurled.knurl_count = 18;
  const Solid nut = make_nut_rsolid(8.0, 13.0, 7.0, knurled);
  CHECK(nut.volume() == Approx(641.4380688591543).epsilon(1e-6));
  CHECK(nut.faces().size() == 48);
}

TEST_CASE("nut: invalid arguments are ValueErrors with the Python text") {
  const auto message = [](double d, double w, double h, NutOptions o = {}) {
    return failure_message([&] { (void)make_nut_rsolid(d, w, h, o); });
  };
  CHECK(message(8.0, 8.2, 6.5) == "width leaves insufficient wall around the nut hole");
  NutOptions castle;
  castle.nut_style = "castle";
  CHECK(message(8.0, 13.0, 6.5, castle) == "nut_style must be one of: hex, knurled, round, square");
  NutOptions through_depth;
  through_depth.hole_depth = 5.0;
  CHECK(message(8.0, 13.0, 6.5, through_depth) == "hole_depth is only valid when hole_style='blind'");
  NutOptions deep;
  deep.hole_style = "blind";
  deep.hole_depth = 6.5;
  CHECK(message(8.0, 13.0, 6.5, deep) == "blind hole_depth must be smaller than height");
  NutOptions coarse;
  coarse.nut_style = "knurled";
  coarse.knurl_count = 6;
  CHECK(message(8.0, 13.0, 6.5, coarse) == "knurl_count must be an integer of at least 8");
}
