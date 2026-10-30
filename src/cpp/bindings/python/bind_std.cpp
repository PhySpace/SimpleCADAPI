// Python bindings for the "std" area: `simplecadapi._cpp.std` with the submodules `gear`, `bearing`,
// `chain` and `fastener`, under the names, argument names and defaults of simplecadapi.std.
//
// The factories record the operations they are built from, not themselves, so there is no
// executor to register: a recorded gear replays through the operators it was made of.
// `build_ball_bearing` (the durable-definition wrapper over the build layer) is not provided.
#include "bindings.hpp"

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/product/assembly.hpp"
#include "scad/product/material.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/std/std.hpp"

namespace {

using namespace scad;

// Runs `body` with the GIL released; an exception leaves with the GIL back.
template <class F>
auto unlocked(F&& body) {
  const py::gil_scoped_release release;
  return body();
}

ToothTuning tuning(double addendum_factor, double clearance_factor, double backlash) {
  return {addendum_factor, clearance_factor, backlash};
}

// `isinstance(value, int) and not isinstance(value, bool)`, as the chain and nut factories test it.
bool is_plain_int(const py::object& value) {
  return PyLong_Check(value.ptr()) != 0 && !PyBool_Check(value.ptr());
}

// `int(value)`, for the arguments Python converts that way.
int python_int(const py::object& value) {
  return py::int_(value).cast<int>();
}

// `str(value)`, the way the fastener factories read their style arguments.
std::string text_of(const py::object& value) {
  return py::str(value).cast<std::string>();
}

py::object point_to_py(const stdlib::Point2& p) {
  return py::make_tuple(p.x, p.y);
}

stdlib::Point2 point_from_py(const py::object& value) {
  const py::sequence items = py::reinterpret_borrow<py::sequence>(value);
  if (items.size() != 2)
    throw ValueError("a 2D point needs two coordinates");
  return {items[0].cast<double>(), items[1].cast<double>()};
}

// ---- gear -----------------------------------------------------------------------------------------------------

void bind_gear_factories(py::module_& gear) {
  gear.def(
      "make_spur_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double gear_height, double addendum_factor,
         double clearance_factor, double backlash) {
        return unlocked([&] {
          return make_spur_gear_rsolid(n_teeth, module, pressure_angle, gear_height,
                                       tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("gear_height") = 6.0,
      py::kw_only(), py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25, py::arg("backlash") = 0.0,
      "Create an involute spur gear (straight teeth, helix angle = 0).\n\n"
      "n_teeth >= 3; module in mm (pitch diameter = module * n_teeth); pressure_angle in degrees;\n"
      "gear_height is the thickness along Z.  addendum_factor and clearance_factor are multiples of\n"
      "the module; backlash is the circumferential tooth-thickness reduction at the pitch circle in mm.");

  gear.def(
      "make_straight_bevel_gear_rsolid",
      [](int n_teeth, double module, double pitch_angle, double pressure_angle, double face_width,
         double addendum_factor, double clearance_factor, double backlash) {
        return unlocked([&] {
          return make_straight_bevel_gear_rsolid(n_teeth, module, pitch_angle, pressure_angle, face_width,
                                                 tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pitch_angle") = 45.0, py::arg("pressure_angle") = 20.0,
      py::arg("face_width") = 8.0, py::kw_only(), py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25,
      py::arg("backlash") = 0.0,
      "Create a straight bevel gear with standard metric tooth proportions.\n\n"
      "The large-end section is the spur-gear involute profile; a similar small-end section sits on the\n"
      "pitch cone and the two are joined with ruled tooth surfaces.  face_width runs along the pitch-cone\n"
      "generator.  Metadata 'std.gear.straight_bevel'.");

  gear.def(
      "make_helical_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double helix_angle, double gear_height,
         double addendum_factor, double clearance_factor, double backlash) {
        return unlocked([&] {
          return make_helical_gear_rsolid(n_teeth, module, pressure_angle, helix_angle, gear_height,
                                          tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 30.0,
      py::arg("gear_height") = 8.0, py::kw_only(), py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25,
      py::arg("backlash") = 0.0,
      "Create an involute helical gear: one continuous twisted sweep along the gear axis (a zero helix\n"
      "angle gives the spur gear).");

  gear.def(
      "make_herringbone_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double helix_angle, double gear_height,
         double addendum_factor, double clearance_factor, double backlash) {
        return unlocked([&] {
          return make_herringbone_gear_rsolid(n_teeth, module, pressure_angle, helix_angle, gear_height,
                                              tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 32.0,
      py::arg("gear_height") = 10.0, py::kw_only(), py::arg("addendum_factor") = 1.0,
      py::arg("clearance_factor") = 0.25, py::arg("backlash") = 0.0,
      "Create an involute herringbone (double-helical) gear: two opposite twisted halves fused at the\n"
      "shared centre section.");

  gear.def(
      "make_spur_ring_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double gear_height, double rim_thickness, double backlash,
         double addendum_factor, double clearance_factor) {
        return unlocked([&] {
          return make_spur_ring_gear_rsolid(n_teeth, module, pressure_angle, gear_height, rim_thickness,
                                            tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("gear_height") = 6.0,
      py::arg("rim_thickness") = 3.0, py::arg("backlash") = 0.0, py::kw_only(), py::arg("addendum_factor") = 1.0,
      py::arg("clearance_factor") = 0.25,
      "Create an internal spur ring gear: the rim circle and the inward tooth profile form one multi-loop\n"
      "face that is extruded directly.  backlash is the circumferential tooth-space clearance at the pitch\n"
      "circle in mm.");

  gear.def(
      "make_helical_ring_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double helix_angle, double gear_height,
         double rim_thickness, double backlash, double addendum_factor, double clearance_factor) {
        return unlocked([&] {
          return make_helical_ring_gear_rsolid(n_teeth, module, pressure_angle, helix_angle, gear_height, rim_thickness,
                                               tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 25.0,
      py::arg("gear_height") = 8.0, py::arg("rim_thickness") = 3.0, py::arg("backlash") = 0.0, py::kw_only(),
      py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25,
      "Create an internal helical ring gear: the multi-loop ring face swept with one continuous twist.");

  gear.def(
      "make_herringbone_ring_gear_rsolid",
      [](int n_teeth, double module, double pressure_angle, double helix_angle, double gear_height,
         double rim_thickness, double backlash, double addendum_factor, double clearance_factor) {
        return unlocked([&] {
          return make_herringbone_ring_gear_rsolid(n_teeth, module, pressure_angle, helix_angle, gear_height,
                                                   rim_thickness, tuning(addendum_factor, clearance_factor, backlash));
        });
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 30.0,
      py::arg("gear_height") = 10.0, py::arg("rim_thickness") = 3.0, py::arg("backlash") = 0.0, py::kw_only(),
      py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25,
      "Create an internal herringbone ring gear: two opposite twisted halves of the ring face, fused.");

  gear.def(
      "make_cycloidal_disc_rsolid",
      [](int n_lobes, double ring_pin_pitch_radius, double roller_radius, double eccentricity, double gear_height,
         double bore_radius, int output_pin_count, double output_pin_pitch_radius, double output_pin_clearance_radius,
         double output_pin_phase, int sample_count_per_lobe, double spline_tolerance, int max_control_points) {
        CycloidalDiscOptions options;
        options.bore_radius = bore_radius;
        options.output_pin_count = output_pin_count;
        options.output_pin_pitch_radius = output_pin_pitch_radius;
        options.output_pin_clearance_radius = output_pin_clearance_radius;
        options.output_pin_phase = output_pin_phase;
        options.sample_count_per_lobe = sample_count_per_lobe;
        options.spline_tolerance = spline_tolerance;
        options.max_control_points = max_control_points;
        return unlocked([&] {
          return make_cycloidal_disc_rsolid(n_lobes, ring_pin_pitch_radius, roller_radius, eccentricity, gear_height,
                                            options);
        });
      },
      py::arg("n_lobes"), py::arg("ring_pin_pitch_radius"), py::arg("roller_radius"), py::arg("eccentricity"),
      py::arg("gear_height") = 6.0, py::kw_only(), py::arg("bore_radius") = 0.0, py::arg("output_pin_count") = 0,
      py::arg("output_pin_pitch_radius") = 0.0, py::arg("output_pin_clearance_radius") = 0.0,
      py::arg("output_pin_phase") = 0.0, py::arg("sample_count_per_lobe") = 33, py::arg("spline_tolerance") = 0.005,
      py::arg("max_control_points") = 20,
      "Create a cycloidal reducer disc for a one-tooth-difference pin ring.\n\n"
      "One fitted cubic B-spline per lobe, an optional central bore and output-pin clearance holes.\n"
      "output_pin_phase (degrees) is read in the unrotated disc's frame.  Metadata 'std.gear.cycloidal_disc'.");

  gear.def(
      "make_spur_rack_rsolid",
      [](double module, int n_teeth, double pressure_angle, double rack_height) {
        return unlocked([&] { return make_spur_rack_rsolid(module, n_teeth, pressure_angle, rack_height); });
      },
      py::arg("module"), py::arg("n_teeth") = 10, py::arg("pressure_angle") = 20.0, py::arg("rack_height") = 6.0,
      "Create a straight-tooth rack (tooth pitch = pi * module, thickness along Z).");

  gear.def(
      "make_helical_rack_rsolid",
      [](double module, int n_teeth, double pressure_angle, double helix_angle, double rack_height) {
        return unlocked(
            [&] { return make_helical_rack_rsolid(module, n_teeth, pressure_angle, helix_angle, rack_height); });
      },
      py::arg("module"), py::arg("n_teeth") = 10, py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 25.0,
      py::arg("rack_height") = 8.0, "Create a helical rack: the rack profile lofted through twisted sections.");

  gear.def(
      "make_herringbone_rack_rsolid",
      [](double module, int n_teeth, double pressure_angle, double helix_angle, double rack_height) {
        return unlocked(
            [&] { return make_herringbone_rack_rsolid(module, n_teeth, pressure_angle, helix_angle, rack_height); });
      },
      py::arg("module"), py::arg("n_teeth") = 10, py::arg("pressure_angle") = 20.0, py::arg("helix_angle") = 30.0,
      py::arg("rack_height") = 10.0, "Create a herringbone rack: two opposite twisted halves lofted as one.");

  gear.attr("__all__") =
      py::make_tuple("make_spur_gear_rsolid", "make_straight_bevel_gear_rsolid", "make_helical_gear_rsolid",
                     "make_herringbone_gear_rsolid", "make_spur_ring_gear_rsolid", "make_helical_ring_gear_rsolid",
                     "make_herringbone_ring_gear_rsolid", "make_cycloidal_disc_rsolid", "make_spur_rack_rsolid",
                     "make_helical_rack_rsolid", "make_herringbone_rack_rsolid");
}

// The private helpers the reference tests reach into (they read the profile sketch and the tooth numbers).
void bind_gear_internals(py::module_& gear) {
  gear.def(
      "_involute_point",
      [](double base_radius, double t) { return point_to_py(stdlib::involute_point(base_radius, t)); },
      py::arg("base_radius"), py::arg("t"));
  gear.def("_involute_t_for_radius", &stdlib::involute_t_for_radius, py::arg("base_radius"), py::arg("target_radius"));
  gear.def(
      "_rotate_xy",
      [](const py::object& point, double angle) { return point_to_py(stdlib::rotate_xy(point_from_py(point), angle)); },
      py::arg("point"), py::arg("angle"));
  gear.def(
      "_root_fillet_control_points",
      [](const py::object& start, const py::object& end, double start_tangent_angle, double end_tangent_angle) {
        const stdlib::BSplineData data = stdlib::root_fillet_control_points(point_from_py(start), point_from_py(end),
                                                                            start_tangent_angle, end_tangent_angle);
        py::list poles;
        for (const stdlib::Point2& pole : data.control_points)
          poles.append(point_to_py(pole));
        return py::make_tuple(poles, data.degree, data.knots, data.multiplicities);
      },
      py::arg("start"), py::arg("end"), py::arg("start_tangent_angle"), py::arg("end_tangent_angle"));

  gear.def(
      "_compute_tooth_geometry",
      [](int n_teeth, double module, double pressure_angle, std::optional<double> root_radius,
         std::optional<double> tip_radius, double addendum_factor, double clearance_factor, double backlash) {
        stdlib::ToothOptions options;
        options.root_radius = root_radius;
        options.tip_radius = tip_radius;
        options.tuning = tuning(addendum_factor, clearance_factor, backlash);
        const stdlib::ToothGeometry g = stdlib::compute_tooth_geometry(n_teeth, module, pressure_angle, options);
        py::dict out;
        out["pitch_radius"] = g.pitch_radius;
        out["base_radius"] = g.base_radius;
        out["tip_radius"] = g.tip_radius;
        out["root_radius"] = g.root_radius;
        out["tooth_angle"] = g.tooth_angle;
        out["left_start"] = g.left_start;
        out["right_start"] = g.right_start;
        out["left_tip_angle"] = g.left_tip_angle;
        out["right_tip_angle"] = g.right_tip_angle;
        out["prev_right_start"] = g.prev_right_start;
        out["addendum_factor"] = g.addendum_factor;
        out["clearance_factor"] = g.clearance_factor;
        out["backlash"] = g.backlash;
        return out;
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle"), py::arg("root_radius") = py::none(),
      py::arg("tip_radius") = py::none(), py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25,
      py::arg("backlash") = 0.0);

  gear.def(
      "_compute_internal_tooth_geometry",
      [](int n_teeth, double module, double pressure_angle, double backlash, double addendum_factor,
         double clearance_factor) {
        const stdlib::InternalToothGeometry g = stdlib::compute_internal_tooth_geometry(
            n_teeth, module, pressure_angle, tuning(addendum_factor, clearance_factor, backlash));
        py::dict out;
        out["pitch_radius"] = g.pitch_radius;
        out["base_radius"] = g.base_radius;
        out["tip_radius"] = g.tip_radius;
        out["root_radius"] = g.root_radius;
        out["flank_tip_radius"] = g.flank_tip_radius;
        out["needs_tip_connectors"] = g.needs_tip_connectors;
        out["tooth_angle"] = g.tooth_angle;
        out["backlash"] = g.backlash;
        out["backlash_half_angle"] = g.backlash_half_angle;
        out["left_base_angle"] = g.left_base_angle;
        out["right_base_angle"] = g.right_base_angle;
        out["left_tip_angle"] = g.left_tip_angle;
        out["right_tip_angle"] = g.right_tip_angle;
        out["left_root_angle"] = g.left_root_angle;
        out["right_root_angle"] = g.right_root_angle;
        out["addendum_factor"] = g.addendum_factor;
        out["clearance_factor"] = g.clearance_factor;
        return out;
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle"), py::arg("backlash") = 0.0,
      py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25);

  gear.def(
      "_internal_ring_radii",
      [](int n_teeth, double module, double rim_thickness, double addendum_factor, double clearance_factor) {
        const stdlib::InternalRingRadii r =
            stdlib::internal_ring_radii(n_teeth, module, rim_thickness, addendum_factor, clearance_factor);
        return py::make_tuple(r.pitch, r.tip, r.root, r.outer);
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("rim_thickness"), py::arg("addendum_factor") = 1.0,
      py::arg("clearance_factor") = 0.25);

  gear.def(
      "_build_gear_profile_face",
      [](int n_teeth, double module, double pressure_angle, bool return_sketch, std::optional<double> root_radius,
         std::optional<double> tip_radius, double addendum_factor, double clearance_factor, double backlash,
         bool build_face) -> py::object {
        stdlib::ToothOptions options;
        options.root_radius = root_radius;
        options.tip_radius = tip_radius;
        options.tuning = tuning(addendum_factor, clearance_factor, backlash);
        Sketch sketch = stdlib::build_gear_profile_sketch(n_teeth, module, pressure_angle, options);
        if (build_face || !return_sketch) {
          Face face = make_face_from_sketch_rface(sketch, 0);
          return return_sketch ? py::make_tuple(py::cast(face), py::cast(std::move(sketch))).cast<py::object>()
                               : py::cast(face);
        }
        return py::make_tuple(py::none(), py::cast(std::move(sketch)));
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle"), py::arg("return_sketch") = false,
      py::arg("root_radius") = py::none(), py::arg("tip_radius") = py::none(), py::arg("addendum_factor") = 1.0,
      py::arg("clearance_factor") = 0.25, py::arg("backlash") = 0.0, py::arg("build_face") = true);

  gear.def(
      "_build_internal_gear_profile_wire",
      [](int n_teeth, double module, double pressure_angle, bool return_sketch, double backlash, double addendum_factor,
         double clearance_factor) -> py::object {
        Sketch sketch = stdlib::build_internal_gear_profile_sketch(n_teeth, module, pressure_angle,
                                                                   tuning(addendum_factor, clearance_factor, backlash));
        Wire wire = make_wire_from_sketch_rwire(sketch, 0);
        if (!return_sketch)
          return py::cast(wire);
        return py::make_tuple(py::cast(wire), py::cast(std::move(sketch)));
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle"), py::arg("return_sketch") = false,
      py::arg("backlash") = 0.0, py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25);

  gear.def(
      "_build_ring_gear_face",
      [](int n_teeth, double module, double pressure_angle, double rim_thickness, double backlash,
         double addendum_factor, double clearance_factor) {
        return stdlib::build_ring_gear_face(n_teeth, module, pressure_angle, rim_thickness,
                                            tuning(addendum_factor, clearance_factor, backlash));
      },
      py::arg("n_teeth"), py::arg("module"), py::arg("pressure_angle"), py::arg("rim_thickness"),
      py::arg("backlash") = 0.0, py::arg("addendum_factor") = 1.0, py::arg("clearance_factor") = 0.25);
}

// ---- chain ----------------------------------------------------------------------------------------------------

void bind_chain(py::module_& chain) {
  chain.def(
      "make_roller_chain_sprocket_rsolid",
      [](const py::object& n_teeth, double chain_pitch, double roller_diameter, double sprocket_thickness,
         double bore_radius, double roller_clearance) {
        if (!is_plain_int(n_teeth))
          throw ValueError("n_teeth must be an integer of at least 6");
        const int teeth = python_int(n_teeth);
        return unlocked([&] {
          return make_roller_chain_sprocket_rsolid(teeth, chain_pitch, roller_diameter, sprocket_thickness, bore_radius,
                                                   roller_clearance);
        });
      },
      py::arg("n_teeth"), py::arg("chain_pitch"), py::arg("roller_diameter"), py::arg("sprocket_thickness"),
      py::kw_only(), py::arg("bore_radius") = 0.0, py::arg("roller_clearance") = 0.15,
      "Create a roller-chain sprocket from the chain engagement dimensions.\n\n"
      "The pitch radius follows the regular pitch polygon; circular roller-seat cutters at every pitch point\n"
      "are opened through the outside-diameter envelope p * (0.6 + cot(180 / z)).  Metadata\n"
      "'std.chain.roller_sprocket' keeps the tooth count, pitch, roller seats, root and outside radii.");
  chain.attr("__all__") = py::make_tuple("make_roller_chain_sprocket_rsolid");
}

// ---- fastener -------------------------------------------------------------------------------------------------

void bind_fastener(py::module_& fastener) {
  fastener.def(
      "make_bolt_rsolid",
      [](double diameter, double length, const py::object& head_style, const py::object& thread_style,
         const py::object& thread_detail, const py::object& thread_form, std::optional<double> thread_pitch,
         std::optional<double> thread_depth, std::optional<double> thread_length, std::optional<double> head_width,
         std::optional<double> head_height, const py::object& drive_style, std::optional<double> drive_size,
         std::optional<double> drive_depth, std::optional<double> underhead_fillet_radius) {
        BoltOptions options;
        options.head_style = text_of(head_style);
        options.thread_style = text_of(thread_style);
        options.thread_detail = text_of(thread_detail);
        options.thread_form = text_of(thread_form);
        options.thread_pitch = thread_pitch;
        options.thread_depth = thread_depth;
        options.thread_length = thread_length;
        options.head_width = head_width;
        options.head_height = head_height;
        options.drive_style = text_of(drive_style);
        options.drive_size = drive_size;
        options.drive_depth = drive_depth;
        options.underhead_fillet_radius = underhead_fillet_radius;
        return unlocked([&] { return make_bolt_rsolid(diameter, length, options); });
      },
      py::arg("diameter"), py::arg("length"), py::arg("head_style") = "hex", py::arg("thread_style") = "auto",
      py::arg("thread_detail") = "modeled", py::arg("thread_form") = "v", py::arg("thread_pitch") = py::none(),
      py::arg("thread_depth") = py::none(), py::arg("thread_length") = py::none(), py::arg("head_width") = py::none(),
      py::arg("head_height") = py::none(), py::arg("drive_style") = "none", py::arg("drive_size") = py::none(),
      py::arg("drive_depth") = py::none(), py::arg("underhead_fillet_radius") = py::none(),
      "Create a bolt along +Z with its head underside on the Z=0 plane.\n\n"
      "head_style accepts hex, square, cylindrical, button and countersunk.  thread_style accepts auto, full,\n"
      "partial and none: auto uses a full thread through 3d length and the standard piecewise partial-thread\n"
      "length above.  Cosmetic threads keep a smooth major-diameter shank and record the thread intent in\n"
      "metadata; modeled threads cut a helical groove.");

  fastener.def(
      "make_nut_rsolid",
      [](double diameter, double width, double height, const py::object& nut_style, const py::object& hole_style,
         const py::object& thread_detail, const py::object& thread_form, std::optional<double> thread_pitch,
         std::optional<double> thread_depth, std::optional<double> hole_depth, const py::object& knurl_count) {
        NutOptions options;
        options.nut_style = text_of(nut_style);
        options.hole_style = text_of(hole_style);
        options.thread_detail = text_of(thread_detail);
        options.thread_form = text_of(thread_form);
        options.thread_pitch = thread_pitch;
        options.thread_depth = thread_depth;
        options.hole_depth = hole_depth;
        // Python reads knurl_count after the dimensions are checked; an invalid count is ValueError either way.
        options.knurl_count = is_plain_int(knurl_count) ? python_int(knurl_count) : -1;
        return unlocked([&] { return make_nut_rsolid(diameter, width, height, options); });
      },
      py::arg("diameter"), py::arg("width"), py::arg("height"), py::arg("nut_style") = "hex",
      py::arg("hole_style") = "through", py::arg("thread_detail") = "modeled", py::arg("thread_form") = "v",
      py::arg("thread_pitch") = py::none(), py::arg("thread_depth") = py::none(), py::arg("hole_depth") = py::none(),
      py::arg("knurl_count") = 24,
      "Create a nut along +Z with its bottom face on the Z=0 plane.\n\n"
      "nut_style accepts hex, square, round and knurled; through and blind holes are supported.  Modeled thread\n"
      "detail adds internal V or trapezoidal helical teeth to a major-diameter hole.");
  fastener.attr("__all__") = py::make_tuple("make_bolt_rsolid", "make_nut_rsolid");
}

// ---- bearing --------------------------------------------------------------------------------------------------

void bind_bearing(py::module_& bearing) {
  bearing.def(
      "make_ball_bearing_rassembly",
      [](double bore_diameter, double outer_diameter, double bearing_width, double ball_diameter,
         const py::object& ball_count, double raceway_clearance, double edge_chamfer, std::string assembly_id,
         std::optional<double> drive_angle_degrees, bool fuse_rolling_elements, double rolling_element_fuse_overlap,
         const py::object& material) {
        BallBearingOptions options;
        if (!ball_count.is_none())
          options.ball_count = python_int(ball_count);
        options.raceway_clearance = raceway_clearance;
        options.edge_chamfer = edge_chamfer;
        options.assembly_id = std::move(assembly_id);
        options.drive_angle_degrees = drive_angle_degrees;
        options.fuse_rolling_elements = fuse_rolling_elements;
        options.rolling_element_fuse_overlap = rolling_element_fuse_overlap;
        if (!material.is_none()) {
          if (!py::isinstance<product::Material>(material))
            throw TypeError("material must be a Material or None");
          options.material = material.cast<const product::Material&>();
        }
        return unlocked([&] {
          return make_ball_bearing_rassembly(bore_diameter, outer_diameter, bearing_width, ball_diameter, options);
        });
      },
      py::arg("bore_diameter"), py::arg("outer_diameter"), py::arg("bearing_width"), py::arg("ball_diameter"),
      py::arg("ball_count") = py::none(), py::arg("raceway_clearance") = 0.02, py::arg("edge_chamfer") = 0.0,
      py::arg("assembly_id") = "ball_bearing", py::arg("drive_angle_degrees") = py::none(),
      py::arg("fuse_rolling_elements") = false, py::arg("rolling_element_fuse_overlap") = 0.01,
      py::arg("material") = py::none(),
      "Create a parameterized radial ball bearing assembly.\n\n"
      "Separate outer_ring, inner_ring and ball_* components, an inner/outer revolute constraint and the public\n"
      "connectors outer_axis / inner_axis.  With fuse_rolling_elements=True the balls are embedded in the outer\n"
      "ring and unioned into it (a simplified body).  `material` is assigned to the generated parts.");
  bearing.attr("__all__") = py::make_tuple("make_ball_bearing_rassembly");
}

}  // namespace

void bind_std(py::module_& m) {
  py::module_ std_module =
      m.def_submodule("std", "Standard parts: gears, bearings, roller-chain sprockets, fasteners.");
  py::module_ gear = std_module.def_submodule("gear", "Involute gears, ring gears, racks and cycloidal discs.");
  py::module_ bearing = std_module.def_submodule("bearing", "Ball bearing standard assemblies.");
  py::module_ chain = std_module.def_submodule("chain", "Roller-chain sprockets.");
  py::module_ fastener = std_module.def_submodule("fastener", "Parameterized bolts and nuts.");

  bind_gear_factories(gear);
  bind_gear_internals(gear);
  bind_bearing(bearing);
  bind_chain(chain);
  bind_fastener(fastener);
  std_module.attr("__all__") = py::make_tuple("bearing", "chain", "fastener", "gear");

  // def_submodule does not register in sys.modules: do it so `import simplecadapi._cpp.std.gear` works.
  py::dict modules = py::module_::import("sys").attr("modules");
  const std::string root = py::str(m.attr("__name__")).cast<std::string>();  // "simplecadapi._cpp._native"
  const std::string package = root.substr(0, root.rfind('.'));               // "simplecadapi._cpp"
  modules[py::str(package + ".std")] = std_module;
  for (const char* name : {"gear", "bearing", "chain", "fastener"}) {
    modules[py::str(package + ".std." + name)] = std_module.attr(name);
  }
}
