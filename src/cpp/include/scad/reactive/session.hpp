// The recording session and the reactive engine.
//
// A `Session` is the C++ GraphSession: installed as the thread's Recorder
// it turns every operation an operator reports into a node of an operation
// DAG, and keeps what the engine needs to run that DAG again:
//
//   * which symbolic scalars (`Var`s and expressions of them) each operation
//     was given;
//   * the outputs of every node, as they are now;
//   * a digest of what each output was computed from.
//
// Editing a parameter is then `set_var(name, value)` + `recompute()`: only the
// nodes that depend on the variable -- and what is downstream of them -- are
// marked dirty, and `recompute` re-runs those, in order, through the
// executors operator areas registered (see registry.hpp).  A node whose
// resolved parameters and input digests come out as before is not re-run; one
// whose key was seen earlier (a slider moved back) reuses the outputs it had.
//
// Thread-compat: a Session and everything it hands out by reference belong to
// one thread at a time (it is installed per thread, like the Recorder it is).
// Give independent models independent Sessions; the executor registry and the
// immutable expression nodes are shared safely between them.
#pragma once

#include <exception>
#include <functional>
#include <list>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/scalar.hpp"
#include "scad/reactive/expr.hpp"
#include "scad/reactive/expr_graph.hpp"
#include "scad/reactive/frame.hpp"
#include "scad/reactive/graph.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/param_ui.hpp"
#include "scad/reactive/registry.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive {

enum class NodeStatus {
  Clean,    // outputs are current
  Dirty,    // a variable upstream changed; the next recompute decides
  Failed,   // the last attempt to recompute raised; outputs are the last good ones
  Blocked,  // not attempted: an input failed
};
std::string_view to_string(NodeStatus status) noexcept;

struct NodeFailure {
  std::string node_id;
  std::string op;
  std::string message;
  std::exception_ptr error;  // a scad::Error naming the operation
};

// What one recompute() did, by node id in graph order.
struct RecomputeReport {
  std::vector<std::string> executed;   // ran its executor
  std::vector<std::string> memoized;   // outputs reused: this exact computation was seen before
  std::vector<std::string> unchanged;  // dirty, but resolved to the same inputs: nothing to do
  std::vector<std::string> blocked;    // not attempted because an input failed
  std::vector<NodeFailure> failed;

  // The nodes whose outputs are new: executed and memoized, in graph order.
  std::vector<std::string> changed;

  bool ok() const noexcept { return failed.empty() && blocked.empty(); }
};

struct RecomputeOptions {
  // Rethrow the first failure once every independent node has been tried.
  bool throw_on_error = false;
};

class Session final : public Recorder {
 public:
  struct Options {
    std::string graph_id;           // random when empty
    std::optional<std::string> ns;  // prefix of every id the session allocates
    // Stamp a durable reference ("topo.ref", the Python SDK's runtime key) on every
    // sub-shape of every output.  Off by default: topo_ref_of() derives the same
    // reference on demand for any sub-shape reached by enumeration, so a face or edge
    // handed to a later operation is still recognised as a pick of its output; stamping
    // costs a pass over each output's topology (about as much as building it).
    bool attach_topology_refs = false;
    // Accept values recorded by other sessions of the same graph id: the node a value came
    // from is found in the process-wide registry (node_registry.hpp) and adopted with its
    // upstream.  Nodes this session records are registered there.  A notebook cell session.
    bool shared_lineage = false;
    // Where an operation was called from (a node's `source`): asked for once per recorded node, with
    // the thread holding whatever it needs.  Empty: nodes carry no source.
    std::function<std::optional<Value>()> source_provider;
    std::size_t memo_capacity = 128;       // computations whose outputs are kept for reuse; 0 = none
    ExecutorRegistry* registry = nullptr;  // nullptr: ExecutorRegistry::global()
  };

  Session() : Session(Options{}) {}
  explicit Session(Options options);
  ~Session() override;
  Session(const Session&) = delete;
  Session& operator=(const Session&) = delete;

  // ---- activation (GraphSession.start / stop) -------------------------------
  // Install this session as the calling thread's recorder and bind its variable
  // values as the ambient bindings.  RuntimeError when already active.  Must be
  // stopped on the thread that started it, in the reverse order of starting.
  void start();
  void stop() noexcept;
  bool active() const noexcept { return scope_.has_value(); }
  // The session started on this thread (get_active_session), even while
  // recording is suspended; nullptr if none.
  static Session* active_session() noexcept;

  // ---- Recorder ------------------------------------------------------------
  // Add the operation to the graph.  ValueError when an input carries lineage
  // from another graph.
  void record(const OpRecord& record, const std::vector<Shape>& outputs) override;
  // The same, returning the node that was added.
  NodePtr record_node(const OpRecord& record, const std::vector<Shape>& outputs);
  // The id of the node the next record will create (a tag assignment's payload names its own node).
  std::optional<NodeReservation> reserve_node(std::string_view prefix) override;
  std::optional<Value> topo_ref_value(const Shape& shape) override;
  // One selection node per picked shape.
  void record_selection(const Shape& source, const std::vector<Shape>& picked, const std::string& kind) override;
  // _ensure_geo_selection_node_ids: the selection nodes of `picked`, a pick of `source`; a pick that
  // already has one keeps it.  Empty when `source` is not a recorded output (the operator then
  // describes its picks by index).
  std::vector<std::string> ensure_selection_nodes(const Shape& source, const std::vector<Shape>& picked);
  // _ensure_geo_selection_input_nodes: a pick used as an input becomes a selection node first.
  void ensure_selection_input_nodes(const std::vector<Shape>& inputs);
  std::optional<Value> input_refs(const std::vector<Shape>& inputs) override;
  // Value inputs found by the lineage their values carry, unless a caller already declared them (expect_value_op).
  std::optional<ValueLineage> record_value_op(const OpRecord& op, const std::vector<ValueLineage>& inputs) override;

  // ---- operations on values that are not shapes ------------------------------
  // The next recorded operation also takes these nodes as inputs (a Part, an Assembly, ... that
  // an earlier node produced) and, when `value_output`, has one output although no shape was
  // produced.  Cleared by the next record and by clear_value_op().
  void expect_value_op(std::vector<NodePtr> inputs, bool value_output);
  void clear_value_op() noexcept;
  // The node the last record added (nullptr before the first).
  const NodePtr& last_node() const noexcept { return last_node_; }
  bool shared_lineage() const noexcept { return options_.shared_lineage; }

  // ---- the recording -------------------------------------------------------
  const OperationGraph& graph() const noexcept { return graph_; }
  ExpressionGraph& expression_graph() noexcept { return expressions_; }
  const ExpressionGraph& expression_graph() const noexcept { return expressions_; }
  FrameGraph& frame_graph() noexcept { return frames_; }
  const FrameGraph& frame_graph() const noexcept { return frames_; }
  ExecutorRegistry& registry() noexcept { return *registry_; }

  // "<ns>_sketch_00000001": a deterministic session-local id.
  std::string allocate_object_id(std::string_view prefix);
  std::optional<std::string> reserve_object_id(std::string_view prefix) override { return allocate_object_id(prefix); }

  // ---- results (capture_result) ---------------------------------------------
  // Mark the nodes the shapes come from as the model's results.  ValueError,
  // and nothing captured, when a shape carries lineage from another graph or
  // none at all.  Returns the node ids now captured.
  std::vector<std::string> capture_result(const std::vector<Shape>& values);
  void clear_results();
  const std::vector<std::string>& result_node_ids() const noexcept { return result_node_ids_; }
  bool has_explicit_results() const noexcept { return has_explicit_results_; }
  // The captured shapes as they are now (after any recompute).
  std::vector<Shape> captured_shapes() const;
  // ValueError when `value` carries lineage from another graph (validate_graph_ownership).
  void validate_graph_ownership(const Shape& value) const;

  // ---- outputs --------------------------------------------------------------
  // What a node produced, as of the last recompute.  KeyError for an unknown id.
  const std::vector<Shape>& outputs(std::string_view node_id) const;
  const Shape& output(std::string_view node_id, int slot = 0) const;
  // The current counterpart of a shape this session produced (or a face/edge of one):
  // the same output after a recompute.  ValueError for a shape it did not record.
  Shape current(const Shape& shape) const;

  // ---- variables ------------------------------------------------------------
  // Make a variable known before any operation uses it (a UI can list it).
  void declare_var(const std::shared_ptr<const Var>& var);
  // The variables recorded operations refer to, in first-use order.
  const std::vector<std::shared_ptr<const Var>>& vars() const noexcept { return vars_; }
  bool has_var(std::string_view name) const noexcept;
  // What an editor lists: one ParamSpec per variable, with the current value as default.
  std::vector<ParamSpec> parameters() const;
  // The value now, in the variable's declared unit: the edit, else the default.
  double var_value(std::string_view name) const;
  const Bindings& bindings() const noexcept { return bindings_; }

  // Change variables.  KeyError for an unknown name; ValueError for a value the
  // variable cannot take (not finite, out of range in canonical units).  The
  // nodes that depend on the variable become Dirty; nothing is recomputed.
  void set_var(std::string_view name, double value);
  void set_vars(const std::vector<std::pair<std::string, double>>& values);  // all or nothing
  void reset_var(std::string_view name);                                     // back to the default
  void reset_vars();

  // ---- change impact --------------------------------------------------------
  // Nodes whose operation was given the variable (graph order).
  std::vector<std::string> nodes_using(std::string_view var_name) const;
  // Those and everything downstream of them: the nodes a change of the
  // variable(s) can alter (graph order).
  std::vector<std::string> affected_nodes(std::string_view var_name) const;
  std::vector<std::string> affected_nodes(const std::vector<std::string>& var_names) const;
  // The variables a node depends on, directly or through what it consumes.
  std::vector<std::string> vars_affecting(std::string_view node_id) const;

  // ---- recomputation --------------------------------------------------------
  NodeStatus status(std::string_view node_id) const;
  std::vector<std::string> dirty_nodes() const;  // every node that is not Clean (graph order)
  // The failure of the last attempt on a node, if it Failed.
  std::exception_ptr failure(std::string_view node_id) const;

  // Re-run what the edits made necessary.  Never throws for an operation that
  // fails (see RecomputeOptions); the report says what happened.
  RecomputeReport recompute(const RecomputeOptions& options = {});

  // Number of computations kept for reuse.
  std::size_t memo_size() const noexcept { return memo_index_.size(); }

 private:
  struct ExternalInput {
    Shape shape;
    std::string token;
  };
  struct NodeState {
    std::vector<Shape> outputs;
    std::string key;  // digest the outputs were computed under
    NodeStatus status = NodeStatus::Clean;
    std::exception_ptr error;
    std::vector<ExternalInput> externals;  // in binding order
    std::vector<std::string> var_names;    // variables the node's own scalars use
    bool value_output = false;             // its one output is a value (a Part, a Sketch): no shape is produced
  };

  NodePtr record_impl(const OpRecord& record, const std::vector<Shape>& outputs, bool selection);
  // The graph node of a shape that is itself a recorded output of this session (adopted when the
  // lineage is shared); nullptr otherwise (_active_graph_node_for_shape).
  NodePtr active_node_for(const Shape& shape);
  NodePtr active_node_for(const Lineage& lineage);
  NodePtr ensure_source_has_own_selection_node(const Shape& source);
  std::optional<Shape> selection_source_for(const Shape& shape);
  std::vector<std::string> record_geo_selection_nodes(const Shape& source, const Shape& selected);
  InputBinding bind_input(const OpInput& input, std::vector<NodePtr>& input_nodes,
                          std::vector<ExternalInput>& externals);
  void attach_outputs(const NodePtr& node, const std::vector<Shape>& outputs, bool selection);
  void note_var_use(const OperationNode& node, NodeState& state);
  std::string node_key(const OperationNode& node, const Value& params) const;
  void mark_dirty(const std::vector<std::string>& node_ids);
  std::vector<std::string> downstream_closure(const std::vector<std::string>& seeds) const;
  NodeState& state_of(std::string_view node_id);
  const NodeState& state_of(std::string_view node_id) const;
  void check_var_value(const Var& var, double value) const;

  // The memo table: node-keyed computations -> outputs, least recently used out first.
  const std::vector<Shape>* memo_find(const std::string& key);
  void memo_insert(const std::string& key, const std::vector<Shape>& outputs);

  OperationGraph graph_;
  ExpressionGraph expressions_;
  FrameGraph frames_;
  Options options_;
  ExecutorRegistry* registry_;
  std::unordered_map<std::string, std::size_t> object_counters_;

  std::unordered_map<std::string, NodeState> states_;
  std::vector<std::shared_ptr<const Var>> vars_;
  std::unordered_map<std::string, std::size_t> var_index_;
  std::unordered_map<std::string, std::vector<std::string>> users_;  // var name -> node ids
  Bindings bindings_;
  std::size_t external_counter_ = 0;

  std::vector<NodePtr> pending_inputs_;
  bool pending_value_output_ = false;
  NodePtr last_node_;
  std::optional<std::pair<std::int64_t, std::int64_t>> pending_source_index_;

  std::vector<std::string> result_node_ids_;
  std::vector<Shape> captured_;
  bool has_explicit_results_ = false;

  using MemoEntry = std::pair<std::string, std::vector<Shape>>;
  std::list<MemoEntry> memo_;
  std::unordered_map<std::string, std::list<MemoEntry>::iterator> memo_index_;

  std::optional<RecorderScope> scope_;
  std::optional<AmbientBindingsScope> ambient_;
  Session* previous_active_ = nullptr;
};

// Run `body` as a top-level build: the caller's session is hidden, recording
// is not suspended and the world coordinate system is current
// (isolated_recording).  Everything is restored on exit.
class IsolatedRecording {
 public:
  IsolatedRecording();
  ~IsolatedRecording();
  IsolatedRecording(const IsolatedRecording&) = delete;
  IsolatedRecording& operator=(const IsolatedRecording&) = delete;

 private:
  Session* previous_;
  RecorderScope recorder_{nullptr};
  CoordinateSystemScope world_{world_cs()};
};

}  // namespace scad::reactive
