// The hook every operator reports through.
//
// An operator that has built its result calls `record_operation`.  With no
// recorder installed that costs one thread-local pointer test.  With one (the
// reactive Session, a model-JSON writer, ...) the operation's name, parameters
// -- symbolic scalars included, so a parameter edit can rerun just this
// operation -- inputs, outputs and topology delta are handed over.
#pragma once

#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// The node a value that is not a shape (a Sketch, a Part, ...) was made by.
struct ValueLineage {
  std::string graph_id;
  std::string node_id;
  int output_slot = 0;
};

struct OpInput {
  Shape shape;
  std::string role;  // "body", "tool", "profile", "path", ...
};

struct OpRecord {
  std::string op;  // the public operator name: "make_box_rsolid"
  Value params;    // JSON-like; numbers are the evaluated values
  // The scalar arguments as given, by parameter name.  Present only for those
  // that were symbolic (Var / Expr): these are what makes replay reactive.
  std::vector<std::pair<std::string, Scalar>> symbolic;
  std::vector<OpInput> inputs;
  // Inputs that are values, not shapes (the Sketch a face is promoted from), by the lineage they carry.
  std::vector<ValueLineage> value_inputs;
  std::optional<TopoDelta> delta;
  std::optional<SemanticDelta> semantic_delta;
  // The node id obtained from Recorder::reserve_node, for operations whose payload
  // names their own node (a tag assignment does); empty = let the recorder number it.
  std::string node_id;
  // Free-form node labels (the `tags=` argument of record_operation_if_active).
  std::vector<std::string> labels;
  // The operation returns a list of shapes that happens to be empty (free_boundaries of a closed shell): its node
  // declares no output.  Without this, an operation that records no shape (a sketch, a value) declares one.
  bool empty_list_result = false;
};

// A node id handed out ahead of the record call.
struct NodeReservation {
  std::string graph_id;
  std::string node_id;
};

class Recorder {
 public:
  virtual ~Recorder() = default;
  // `outputs` are the operation's result shapes, in output-slot order.
  virtual void record(const OpRecord& record, const std::vector<Shape>& outputs) = 0;
  // An operation whose inputs and result are values that are not shapes.  `inputs` are the lineages of its value
  // inputs; the answer is the lineage the result value takes (nullopt: attach nothing).  A recorder without values
  // records the operation alone.
  virtual std::optional<ValueLineage> record_value_op(const OpRecord& op, const std::vector<ValueLineage>& inputs) {
    (void)inputs;
    record(op, {});
    return std::nullopt;
  }
  // Selections (indexed picks) are recorded as graph nodes too.
  virtual void record_selection(const Shape& source, const std::vector<Shape>& picked, const std::string& kind) {
    (void)source;
    (void)picked;
    (void)kind;
  }
  // A session-local object id ("<graph>_sketch_00000001"): what an object made without an id of its own is
  // named, so that rebuilding a session names it the same.  nullopt: this recorder names nothing.
  virtual std::optional<std::string> reserve_object_id(std::string_view prefix) {
    (void)prefix;
    return std::nullopt;
  }
  // Reserve the id of the node the next `record` call will create (id prefix "n"), so
  // that a payload can refer to its own node.  Recorders that do not number nodes ahead
  // of time answer nullopt and the payload is built without it.
  virtual std::optional<NodeReservation> reserve_node(std::string_view prefix) {
    (void)prefix;
    return std::nullopt;
  }

  // The durable reference of a shape this recorder recorded (graph_id, node_id, output_slot, kind,
  // topo_id in the SDK's text), for evidence that names shapes; nullopt when it knows none.
  virtual std::optional<Value> topo_ref_value(const Shape& shape) {
    (void)shape;
    return std::nullopt;
  }

  // `input_refs` of an operation that records its ordered inputs as references: every input that is a
  // pick without a graph node of its own gets one first, then each input is written as its topology
  // reference with a selector hint.  nullopt when this recorder keeps no references.
  virtual std::optional<Value> input_refs(const std::vector<Shape>& inputs) {
    (void)inputs;
    return std::nullopt;
  }

  // Ids reserved through reserve_semantic_id (semantic/finalize.hpp), by kind: part,
  // assembly, material ...  They are unique within one recorded session.
  std::map<std::string, std::set<std::string>> semantic_ids;
};

// The recorder active on this thread, or nullptr.
Recorder* current_recorder() noexcept;

// RAII: install `recorder` on this thread for the scope's lifetime (nests).
class RecorderScope {
 public:
  explicit RecorderScope(Recorder* recorder) noexcept;
  ~RecorderScope();
  RecorderScope(const RecorderScope&) = delete;
  RecorderScope& operator=(const RecorderScope&) = delete;

 private:
  Recorder* previous_;
};

// Suspend recording on this thread (suspend_graph_recording): internal helper
// operations that must not appear as graph nodes use this.
class RecorderSuspend {
 public:
  RecorderSuspend() noexcept : scope_(nullptr) {}

 private:
  RecorderScope scope_;
};

inline void record_operation(const OpRecord& record, const std::vector<Shape>& outputs) {
  if (Recorder* r = current_recorder())
    r->record(record, outputs);
}

}  // namespace scad
