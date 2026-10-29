// Synthetic operations for the engine tests: a box, a translation and a pair,
// recorded and executable like the real operators will be.
#pragma once

#include <algorithm>
#include <map>
#include <string>

#include <BRepBuilderAPI_Transform.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Trsf.hxx>

#include "scad/core/error.hpp"
#include "scad/reactive/registry.hpp"
#include "scad/reactive/session.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive::testing {

inline Solid build_box(double w, double h, double d) {
  return Solid(BRepPrimAPI_MakeBox(w, h, d).Shape());
}

inline Shape build_translated(const Shape& shape, double dx) {
  gp_Trsf move;
  move.SetTranslation(gp_Vec(dx, 0, 0));
  return Shape::from_occt(BRepBuilderAPI_Transform(shape.wrapped(), move, true).Shape());
}

inline Compound build_pair(const Shape& a, const Shape& b) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  builder.Add(compound, a.wrapped());
  builder.Add(compound, b.wrapped());
  return Compound(compound);
}

inline Solid pick_sized(const Shape& shape, double scale) {
  const auto box = shape.bounding_box();
  return build_box(std::max(box.xlen() * scale, 0.5), std::max(box.ylen() * scale, 0.5), box.zlen() * scale + 1.0);
}

class Fixture {
 public:
  Fixture() {
    registry.add("synth_box", [this](const Value& p, const std::vector<OpInput>&, const ScalarValues&) {
      ++calls["synth_box"];
      const double w = p.find("width")->as_double(), h = p.find("height")->as_double(),
                   d = p.find("depth")->as_double();
      if (w <= 0 || h <= 0 || d <= 0)
        throw ValueError("box sizes must be positive");
      return std::vector<Shape>{build_box(w, h, d)};
    });
    registry.add("synth_translate", [this](const Value& p, const std::vector<OpInput>& in, const ScalarValues&) {
      ++calls["synth_translate"];
      return std::vector<Shape>{build_translated(in.at(0).shape, p.find("dx")->as_double())};
    });
    registry.add("synth_pair", [this](const Value&, const std::vector<OpInput>& in, const ScalarValues&) {
      ++calls["synth_pair"];
      return std::vector<Shape>{build_pair(in.at(0).shape, in.at(1).shape)};
    });
    registry.add("synth_pick_box", [this](const Value& p, const std::vector<OpInput>& in, const ScalarValues&) {
      // A "feature" that needs a picked face: a box as wide as the face is.
      ++calls["synth_pick_box"];
      const double scale = p.find("scale")->as_double();
      return std::vector<Shape>{pick_sized(in.at(0).shape, scale)};
    });
  }

  Session::Options options() {
    Session::Options o;
    o.registry = &registry;
    return o;
  }

  Solid box(const Scalar& w, const Scalar& h, const Scalar& d) {
    const double wv = evaluate_scalar(w, "width"), hv = evaluate_scalar(h, "height"), dv = evaluate_scalar(d, "depth");
    Solid out = build_box(wv, hv, dv);
    OpRecord rec;
    rec.op = "synth_box";
    rec.params = Value::object();
    rec.params.set("width", wv);
    rec.params.set("height", hv);
    rec.params.set("depth", dv);
    if (w.symbolic())
      rec.symbolic.emplace_back("width", w);
    if (h.symbolic())
      rec.symbolic.emplace_back("height", h);
    if (d.symbolic())
      rec.symbolic.emplace_back("depth", d);
    record_operation(rec, {out});
    return out;
  }

  Shape translate(const Shape& shape, const Scalar& dx) {
    const double dv = evaluate_scalar(dx, "dx");
    Shape out = build_translated(shape, dv);
    OpRecord rec;
    rec.op = "synth_translate";
    rec.params = Value::object();
    rec.params.set("dx", dv);
    if (dx.symbolic())
      rec.symbolic.emplace_back("dx", dx);
    rec.inputs.push_back(OpInput{shape, "body"});
    record_operation(rec, {out});
    return out;
  }

  Compound pair(const Shape& a, const Shape& b) {
    Compound out = build_pair(a, b);
    OpRecord rec;
    rec.op = "synth_pair";
    rec.inputs.push_back(OpInput{a, "body"});
    rec.inputs.push_back(OpInput{b, "tool"});
    record_operation(rec, {out});
    return out;
  }

  // A box sized by a picked face's extent.
  Solid pick_box(const Shape& face, double scale) {
    Solid out = pick_sized(face, scale);
    OpRecord rec;
    rec.op = "synth_pick_box";
    rec.params = Value::object();
    rec.params.set("scale", scale);
    rec.inputs.push_back(OpInput{face, "face"});
    record_operation(rec, {out});
    return out;
  }

  ExecutorRegistry registry;
  std::map<std::string, int> calls;
};

}  // namespace scad::reactive::testing
