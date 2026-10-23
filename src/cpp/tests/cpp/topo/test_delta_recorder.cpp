#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>

#include "scad/topo/delta.hpp"
#include "scad/topo/recorder.hpp"

using namespace scad;

namespace {

struct Capture : Recorder {
  std::vector<std::string> ops;
  std::size_t outputs = 0;
  void record(const OpRecord& r, const std::vector<Shape>& out) override {
    ops.push_back(r.op);
    outputs += out.size();
  }
};

Solid unit_box() { return Solid(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Solid()); }

}  // namespace

TEST_CASE("record_operation is a no-op without a recorder") {
  CHECK(current_recorder() == nullptr);
  OpRecord rec;
  rec.op = "make_box_rsolid";
  record_operation(rec, {unit_box()});  // must not crash
}

TEST_CASE("recorders nest and unwind per thread") {
  Capture outer, inner;
  {
    RecorderScope a(&outer);
    OpRecord rec;
    rec.op = "outer_op";
    record_operation(rec, {unit_box()});
    {
      RecorderScope b(&inner);
      rec.op = "inner_op";
      record_operation(rec, {unit_box(), unit_box()});
      {
        RecorderSuspend suspended;
        rec.op = "hidden";
        record_operation(rec, {unit_box()});
      }
      CHECK(current_recorder() == &inner);
    }
    CHECK(current_recorder() == &outer);
  }
  CHECK(current_recorder() == nullptr);
  CHECK(outer.ops == std::vector<std::string>{"outer_op"});
  CHECK(inner.ops == std::vector<std::string>{"inner_op"});
  CHECK(inner.outputs == 2);
}

TEST_CASE("binding a delta fills only the pending ids") {
  TopoDelta delta;
  TopoRef pending;
  pending.topo_id = "face_0";
  TopoRef bound = pending;
  bound.graph_id = "g1";
  bound.node_id = "n0";
  delta.generated = {pending};
  delta.preserved = {bound};
  const TopoDelta out = bind_topo_delta(delta, "g2", "n9");
  CHECK(out.generated[0].graph_id == "g2");
  CHECK(out.generated[0].node_id == "n9");
  CHECK(out.preserved[0].graph_id == "g1");
  CHECK(out.preserved[0].node_id == "n0");
  CHECK(to_value(out).dump().find("\"generated\":[{\"graph_id\":\"g2\"") != std::string::npos);
}
