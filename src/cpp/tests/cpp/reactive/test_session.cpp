// The recorder and the reactive engine, driven by synthetic operations.
#include "doctest.h"

#include <algorithm>

#include "fixture.hpp"
#include "scad/reactive/lineage.hpp"

using namespace scad;
using namespace scad::reactive;
using namespace scad::reactive::testing;

namespace {

bool has(const std::vector<std::string>& ids, const std::string& id) {
  return std::find(ids.begin(), ids.end(), id) != ids.end();
}

std::string node_of(const Shape& shape) { return lineage_of(shape)->node_id; }

// boxA(w, h, d) and boxB are joined by a pair after boxA is translated by dx.
struct Model {
  Fixture fx;
  Session session{fx.options()};
  Sym w = make_var("w", 10.0, "width", std::nullopt, units::mm());
  Sym h = make_var("h", 20.0);
  Sym d = make_var("d", 30.0);
  Sym dx = make_var("dx", 5.0);
  Solid box_a{build_box(1, 1, 1)}, box_b{build_box(1, 1, 1)};
  Shape moved{build_box(1, 1, 1)};
  Shape both{build_box(1, 1, 1)};

  Model() {
    session.start();
    box_a = fx.box(w, h, d);
    box_b = fx.box(4.0, 4.0, 4.0);
    moved = fx.translate(box_a, dx);
    both = fx.pair(moved, box_b);
    session.stop();
  }
  double volume_of(const Shape& shape) { return Compound(session.current(shape)).volume(); }
};

}  // namespace

TEST_CASE("recording builds the operation graph and tags the outputs") {
  Model m;
  const OperationGraph& g = m.session.graph();
  CHECK(g.node_count() == 4);
  CHECK(g.edge_count() == 3);
  CHECK(g.is_dag());
  CHECK(g.root_nodes().size() == 2);
  CHECK(g.leaf_nodes().size() == 1);

  const std::string a = node_of(m.box_a), b = node_of(m.box_b), t = node_of(m.moved), p = node_of(m.both);
  CHECK(a == "node_00000001");
  CHECK(g.get_node(a)->op == "synth_box");
  CHECK(g.get_node(a)->params.find("width")->as_double() == 10.0);
  CHECK(g.get_node(a)->symbolic.size() == 3);
  CHECK(g.get_node(b)->symbolic.empty());
  CHECK(g.upstream_nodes(t) == std::vector<std::string>{a});
  CHECK(g.upstream_nodes(p) == std::vector<std::string>{t, b});
  CHECK(g.get_node(p)->bindings.size() == 2);
  CHECK(g.get_node(p)->bindings[1].role == "tool");
  CHECK(lineage_of(m.box_a)->graph_id == g.graph_id());
  CHECK(lineage_of(m.box_a)->output_slot == 0);

  // The expressions are registered and param_exprs says where they sit.
  CHECK(m.session.expression_graph().node_count() == 4);
  const NodePtr node_a = g.get_node(a);
  CHECK(node_a->param_exprs.find("width")->find("expr_id")->as_string() == m.w.expr_id());
  CHECK(node_a->param_exprs.find("height")->find("expr_id")->as_string() == m.h.expr_id());
  CHECK(node_a->expressions.size() == 3);
  CHECK(node_a->context->find("origin") != nullptr);
  CHECK(m.session.frame_graph().node_count() == 4);
  CHECK(m.session.frame_graph().get("frame:" + a) != nullptr);

  // Sub-shapes carry durable references to the node that made them.
  const auto face = Solid(m.box_a).faces().front();
  const auto ref = topo_ref_of(face);
  REQUIRE(ref);
  CHECK(ref->node_id == a);
  CHECK(ref->kind == Kind::Face);
}

TEST_CASE("editing a variable recomputes only what depends on it") {
  Model m;
  const std::string a = node_of(m.box_a), b = node_of(m.box_b), t = node_of(m.moved), p = node_of(m.both);
  m.fx.calls.clear();

  m.session.set_var("w", 20.0);
  CHECK(m.session.status(a) == NodeStatus::Dirty);
  CHECK(m.session.status(t) == NodeStatus::Dirty);
  CHECK(m.session.status(p) == NodeStatus::Dirty);
  CHECK(m.session.status(b) == NodeStatus::Clean);
  CHECK(m.session.dirty_nodes() == std::vector<std::string>{a, t, p});

  const RecomputeReport report = m.session.recompute();
  CHECK(report.ok());
  CHECK(report.executed == std::vector<std::string>{a, t, p});
  CHECK(report.changed == report.executed);
  CHECK(m.fx.calls["synth_box"] == 1);
  CHECK(m.fx.calls["synth_translate"] == 1);
  CHECK(m.fx.calls["synth_pair"] == 1);
  CHECK(m.session.dirty_nodes().empty());

  CHECK(Solid(m.session.output(a)).volume() == doctest::Approx(20.0 * 20.0 * 30.0));
  CHECK(Solid(m.session.current(m.box_a)).volume() == doctest::Approx(12000.0));
  CHECK(m.volume_of(m.both) == doctest::Approx(12000.0 + 64.0));
  CHECK(m.session.var_value("w") == 20.0);
  // The handle the user holds still describes the old model.
  CHECK(m.box_a.volume() == doctest::Approx(10.0 * 20.0 * 30.0));

  // An edit that touches only the translation leaves the boxes alone.
  m.fx.calls.clear();
  m.session.set_var("dx", 50.0);
  const RecomputeReport second = m.session.recompute();
  CHECK(second.executed == std::vector<std::string>{t, p});
  CHECK(m.fx.calls["synth_box"] == 0);
  const auto box = Shape(m.session.current(m.moved)).bounding_box();
  CHECK(box.xmin == doctest::Approx(50.0));
}

TEST_CASE("an edit that is undone before recompute costs nothing") {
  Model m;
  m.fx.calls.clear();
  m.session.set_var("h", 99.0);
  m.session.set_var("h", 20.0);  // back to the value the model was built with
  const RecomputeReport report = m.session.recompute();
  CHECK(report.executed.empty());
  CHECK(report.memoized.empty());
  CHECK(report.unchanged.size() == 3);  // dirty by reach, found equal by digest
  CHECK(m.fx.calls.empty());
  CHECK(m.session.dirty_nodes().empty());

  m.session.set_var("h", 20.0);  // the same value again: not even dirty
  CHECK(m.session.dirty_nodes().empty());
}

TEST_CASE("a computation seen before is reused, not run again") {
  Model m;
  const std::string a = node_of(m.box_a);
  m.session.set_var("w", 20.0);
  m.session.recompute();
  const Shape at_twenty = m.session.output(a);
  m.fx.calls.clear();

  m.session.set_var("w", 10.0);
  const RecomputeReport back = m.session.recompute();
  CHECK(back.executed.empty());
  CHECK(back.memoized.size() == 3);
  CHECK(m.fx.calls.empty());
  CHECK(m.session.output(a).same_entity(m.box_a));  // the very objects of the first build
  CHECK(m.session.output(a).topo_id() == m.box_a.topo_id());

  m.session.set_var("w", 20.0);
  m.session.recompute();
  CHECK(m.fx.calls.empty());
  CHECK(m.session.output(a).same_entity(at_twenty));
  CHECK(m.session.memo_size() >= 3);
}

TEST_CASE("a value that resolves to the same parameters stops the propagation") {
  Fixture fx;
  Session session(fx.options());
  const Sym x = make_var("x", 5.0);
  session.start();
  const Solid box = fx.box(abs(x), 2.0, 2.0);
  const Shape moved = fx.translate(box, 1.0);
  session.stop();
  fx.calls.clear();
  session.set_var("x", -5.0);  // |x| is still 5
  const RecomputeReport report = session.recompute();
  CHECK(report.executed.empty());
  CHECK(report.unchanged.size() == 2);
  CHECK(fx.calls.empty());
}

TEST_CASE("a failing node blocks its dependents and nothing else") {
  Model m;
  const std::string a = node_of(m.box_a), b = node_of(m.box_b), t = node_of(m.moved), p = node_of(m.both);
  m.session.set_vars({{"w", -1.0}, {"dx", 1.0}});
  const RecomputeReport report = m.session.recompute();
  CHECK_FALSE(report.ok());
  REQUIRE(report.failed.size() == 1);
  CHECK(report.failed[0].node_id == a);
  CHECK(report.failed[0].op == "synth_box");
  CHECK(report.blocked == std::vector<std::string>{t, p});
  CHECK(m.session.status(a) == NodeStatus::Failed);
  CHECK(m.session.status(t) == NodeStatus::Blocked);
  CHECK(m.session.status(b) == NodeStatus::Clean);
  CHECK(Solid(m.session.output(a)).volume() == doctest::Approx(6000.0));  // the last good result

  // The error is a scad::Error under the operation's name.
  try {
    std::rethrow_exception(m.session.failure(a));
    FAIL("expected an exception");
  } catch (const Error& e) {
    CHECK(e.operation() == "synth_box");
    CHECK(std::string(e.what()).find("box sizes must be positive") != std::string::npos);
  }

  m.session.set_var("w", 7.0);
  const RecomputeReport fixed = m.session.recompute();
  CHECK(fixed.ok());
  CHECK(m.session.dirty_nodes().empty());
  CHECK(Solid(m.session.output(a)).volume() == doctest::Approx(7.0 * 20.0 * 30.0));

  m.session.set_var("w", -2.0);
  CHECK_THROWS_AS(m.session.recompute({.throw_on_error = true}), Error);
}

TEST_CASE("an operation with no executor is reported by name") {
  Fixture fx;
  Session session(fx.options());
  const Sym x = make_var("x", 5.0);
  session.start();
  OpRecord rec;
  rec.op = "unregistered_op";
  rec.params = Value::object();
  rec.params.set("size", 5.0);
  rec.symbolic.emplace_back("size", x.scalar());
  record_operation(rec, {build_box(1, 1, 1)});
  session.stop();
  session.set_var("x", 6.0);
  const RecomputeReport report = session.recompute();
  REQUIRE(report.failed.size() == 1);
  CHECK(report.failed[0].message.find("unregistered_op") != std::string::npos);
  CHECK(report.failed[0].message.find("no executor is registered") != std::string::npos);
}

TEST_CASE("change-impact queries") {
  Model m;
  const std::string a = node_of(m.box_a), t = node_of(m.moved), p = node_of(m.both);
  CHECK(m.session.nodes_using("w") == std::vector<std::string>{a});
  CHECK(m.session.affected_nodes("w") == std::vector<std::string>{a, t, p});
  CHECK(m.session.affected_nodes("dx") == std::vector<std::string>{t, p});
  CHECK(m.session.affected_nodes(std::vector<std::string>{"dx", "h"}) == std::vector<std::string>{a, t, p});
  CHECK(m.session.vars_affecting(p) == std::vector<std::string>{"w", "h", "d", "dx"});
  CHECK(m.session.vars_affecting(node_of(m.box_b)).empty());
  CHECK(m.session.vars_affecting(t) == std::vector<std::string>{"w", "h", "d", "dx"});
  CHECK_THROWS_AS(m.session.affected_nodes("nope"), KeyError);
  CHECK_THROWS_AS(m.session.vars_affecting("nope"), KeyError);
  CHECK(m.session.nodes_using("w") == m.session.nodes_using("w"));
  CHECK(m.session.vars().size() == 4);
}

TEST_CASE("variables validate and keep their unit") {
  Model m;
  CHECK_THROWS_AS(m.session.set_var("missing", 1.0), KeyError);
  CHECK_THROWS_AS(m.session.set_var("w", HUGE_VAL), ValueError);
  CHECK_THROWS_AS(m.session.set_vars({{"w", 2.0}, {"missing", 1.0}}), KeyError);
  CHECK(m.session.var_value("w") == 10.0);  // all or nothing
  CHECK(m.session.dirty_nodes().empty());

  m.session.reset_var("w");  // nothing to undo
  m.session.set_var("w", 11.0);
  CHECK(m.session.var_value("w") == 11.0);
  m.session.reset_vars();
  CHECK(m.session.var_value("w") == 10.0);
  CHECK(m.session.bindings().empty());

  const auto specs = m.session.parameters();
  REQUIRE(specs.size() == 4);
  CHECK(specs[0].name == "w");
  CHECK(specs[0].declared == "var");
  CHECK(specs[0].unit == std::optional<std::string>("mm"));
  CHECK(specs[0].comment == std::optional<std::string>("width"));
}

TEST_CASE("a variable with a unit reaches the executor in canonical units") {
  Fixture fx;
  Session session(fx.options());
  const Sym width = make_var("width", 1.0, std::nullopt, std::nullopt, units::inch());
  session.start();
  const Solid box = fx.box(width, 2.0, 3.0);
  session.stop();
  const std::string a = node_of(box);
  CHECK(session.graph().get_node(a)->params.find("width")->as_double() == doctest::Approx(25.4));
  session.set_var("width", 2.0);  // inches
  session.recompute();
  CHECK(Solid(session.output(a)).bounding_box().xlen() == doctest::Approx(50.8));
}

TEST_CASE("recording after an edit uses the edited value") {
  Fixture fx;
  Session session(fx.options());
  const Sym w = make_var("w", 10.0);
  session.start();
  const Solid first = fx.box(w, 1.0, 1.0);
  session.set_var("w", 25.0);
  const Solid second = fx.box(w, 1.0, 1.0);  // the operator evaluates through the ambient bindings
  session.stop();
  CHECK(first.bounding_box().xlen() == doctest::Approx(10.0));
  CHECK(second.bounding_box().xlen() == doctest::Approx(25.0));
  CHECK(session.graph().get_node(node_of(second))->params.find("width")->as_double() == 25.0);
  // The first box is now stale relative to the edit.
  CHECK(session.status(node_of(first)) == NodeStatus::Dirty);
  CHECK(session.recompute().executed == std::vector<std::string>{node_of(first)});
  CHECK(Solid(session.output(node_of(first))).bounding_box().xlen() == doctest::Approx(25.0));
}

TEST_CASE("a face picked from an output becomes a selection and follows its source") {
  Fixture fx;
  Session session(fx.options());
  const Sym w = make_var("w", 10.0);
  session.start();
  const Solid box = fx.box(w, 20.0, 30.0);
  const auto faces = box.faces();
  const auto found = std::find_if(faces.begin(), faces.end(), [](const Face& face) { return face.bounding_box().zmin > 29.0; });
  REQUIRE(found != faces.end());
  const Face top = *found;
  const Solid derived = fx.pick_box(top, 1.0);
  session.stop();

  REQUIRE(session.graph().node_count() == 3);
  const NodePtr selection = session.graph().get_node(node_of(top));
  CHECK(selection->op == "make_select_rface");
  CHECK(selection->inputs.size() == 1);
  const Value* selector = selection->params.find("geo_selector");
  REQUIRE(selector != nullptr);
  CHECK(selector->find("mode")->as_string() == "geo_exact");
  CHECK(selector->find("kind")->as_string() == "face");
  const Value* bbox = selector->find("bbox");
  REQUIRE(bbox != nullptr);
  CHECK(bbox->find("min") != nullptr);
  CHECK(bbox->find("max") != nullptr);
  CHECK(session.graph().get_node(node_of(derived))->bindings[0].node_id == selection->node_id);

  session.set_var("w", 40.0);
  const RecomputeReport report = session.recompute();
  CHECK(report.executed.size() == 3);  // box, the selection, the feature
  CHECK(fx.calls["synth_pick_box"] == 1);
  // The picked face is the top face of the rebuilt box, 40 wide.
  CHECK(Shape(session.current(top)).bounding_box().xlen() == doctest::Approx(40.0));
  CHECK(Shape(session.current(derived)).bounding_box().xlen() == doctest::Approx(40.0));
}

TEST_CASE("an explicitly recorded selection is a node of its own, once") {
  Fixture fx;
  Session session(fx.options());
  session.start();
  const Solid box = fx.box(1.0, 2.0, 3.0);
  const Face face = box.faces().front();
  current_recorder()->record_selection(box, {face}, "face");
  current_recorder()->record_selection(box, {face}, "face");
  session.stop();
  CHECK(session.graph().node_count() == 2);
  CHECK(session.graph().get_node(node_of(face))->op == "make_select_rface");
}

TEST_CASE("an unrecorded shape is a constant input") {
  Fixture fx;
  Session session(fx.options());
  const Sym dx = make_var("dx", 1.0);
  const Solid imported = build_box(2, 2, 2);
  session.start();
  const Shape moved = fx.translate(imported, dx);
  session.stop();
  const NodePtr node = session.graph().get_node(node_of(moved));
  CHECK(node->inputs.empty());
  REQUIRE(node->bindings.size() == 1);
  CHECK(node->bindings[0].external());
  session.set_var("dx", 8.0);
  CHECK(session.recompute().ok());
  const auto box = Shape(session.current(moved)).bounding_box();
  CHECK(box.xmin == doctest::Approx(8.0));
  CHECK(box.xlen() == doctest::Approx(2.0));
}

TEST_CASE("lineage from another session is refused") {
  Fixture fx;
  Session::Options first_options = fx.options();
  first_options.graph_id = "source";
  Session first(first_options);
  first.start();
  const Solid foreign = fx.box(1.0, 1.0, 1.0);
  first.stop();

  Session::Options second_options = fx.options();
  second_options.graph_id = "target";
  Session second(second_options);
  second.start();
  try {
    fx.translate(foreign, 1.0);
    FAIL("expected a ValueError");
  } catch (const ValueError& e) {
    const std::string text = e.what();
    CHECK(text.find("source") != std::string::npos);
    CHECK(text.find("target") != std::string::npos);
  }
  second.stop();
  CHECK(second.graph().node_count() == 0);
  // A face of the foreign shape is refused the same way.
  second.start();
  CHECK_THROWS_AS(fx.pick_box(foreign.faces().front(), 1.0), ValueError);
  second.stop();
}

TEST_CASE("capture_result marks the model's results and is atomic") {
  Fixture fx;
  Session::Options options = fx.options();
  options.graph_id = "explicit_session";
  Session session(options);
  const Sym w = make_var("w", 3.0);
  session.start();
  fx.box(0.5, 0.5, 0.5);
  const Solid result = fx.box(w, 2.0, 3.0);
  session.stop();

  CHECK(session.graph().graph_id() == "explicit_session");
  CHECK_FALSE(session.has_explicit_results());
  CHECK(session.capture_result({result}) == std::vector<std::string>{node_of(result)});
  CHECK(session.has_explicit_results());
  CHECK(session.result_node_ids() == std::vector<std::string>{node_of(result)});

  Session other(fx.options());
  other.start();
  const Solid foreign = fx.box(2.0, 2.0, 2.0);
  other.stop();
  Session atomic(fx.options());
  atomic.start();
  const Solid mine = fx.box(1.0, 1.0, 1.0);
  atomic.stop();
  CHECK_THROWS_AS(atomic.capture_result({mine, foreign}), ValueError);
  CHECK_FALSE(atomic.has_explicit_results());
  CHECK(atomic.result_node_ids().empty());
  CHECK_THROWS_AS(atomic.capture_result({build_box(1, 1, 1)}), ValueError);  // not graph-backed

  session.set_var("w", 9.0);
  session.recompute();
  CHECK(Solid(session.captured_shapes().at(0)).bounding_box().xlen() == doctest::Approx(9.0));
  session.clear_results();
  CHECK_FALSE(session.has_explicit_results());
  CHECK(session.captured_shapes().empty());
}

TEST_CASE("activation, suspension and isolation") {
  Fixture fx;
  Session session(fx.options());
  CHECK(Session::active_session() == nullptr);
  CHECK_FALSE(session.active());
  session.start();
  CHECK(session.active());
  CHECK(Session::active_session() == &session);
  CHECK(current_recorder() == &session);
  CHECK_THROWS_AS(session.start(), RuntimeError);

  fx.box(1.0, 1.0, 1.0);
  {
    const RecorderSuspend suspended;  // suspend_graph_recording
    CHECK(Session::active_session() == &session);
    fx.box(2.0, 2.0, 2.0);
  }
  CHECK(session.graph().node_count() == 1);
  {
    const IsolatedRecording isolated;
    CHECK(Session::active_session() == nullptr);
    CHECK(current_recorder() == nullptr);
    fx.box(3.0, 3.0, 3.0);
  }
  CHECK(Session::active_session() == &session);
  CHECK(session.graph().node_count() == 1);

  Session inner(fx.options());
  inner.start();
  CHECK(Session::active_session() == &inner);
  fx.box(4.0, 4.0, 4.0);
  inner.stop();
  CHECK(Session::active_session() == &session);
  CHECK(inner.graph().node_count() == 1);
  CHECK(session.graph().node_count() == 1);
  session.stop();
  CHECK(Session::active_session() == nullptr);
  CHECK(current_recorder() == nullptr);
}

TEST_CASE("operations recorded in a workplane recompute in it") {
  Fixture fx;
  fx.registry.replace("synth_where", [](const Value&, const std::vector<OpInput>&, const ScalarValues&) {
    return std::vector<Shape>{build_translated(build_box(1, 1, 1), current_cs().origin().z)};
  });
  Session session(fx.options());
  session.start();
  const Sym x = make_var("x", 1.0);
  Shape shape = build_translated(build_box(1, 1, 1), 0.0);
  {
    Workplane plane({0, 0, 7}, {0, 0, 1}, {1, 0, 0});
    plane.enter();
    OpRecord rec;
    rec.op = "synth_where";
    rec.params = Value::object();
    rec.params.set("x", 1.0);
    rec.symbolic.emplace_back("x", x.scalar());
    record_operation(rec, {shape});
    plane.exit();
  }
  session.stop();
  session.set_var("x", 2.0);
  CHECK(session.recompute().ok());
  CHECK(Shape(session.current(shape)).bounding_box().xmin == doctest::Approx(7.0));  // placed through z = 7
}

TEST_CASE("the executor registry") {
  ExecutorRegistry registry(false);
  CHECK(registry.operations().empty());
  const Executor noop = [](const Value&, const std::vector<OpInput>&, const ScalarValues&) { return std::vector<Shape>{}; };
  registry.add("one", noop);
  CHECK_THROWS_AS(registry.add("one", noop), ValueError);
  CHECK_THROWS_AS(registry.add("empty", Executor{}), ValueError);
  registry.replace("one", noop);
  CHECK(registry.contains("one"));
  CHECK(registry.find("one"));
  CHECK_FALSE(registry.find("two"));
  CHECK(registry.remove("one"));
  CHECK_FALSE(registry.remove("one"));

  ExecutorRegistry with_builtins;
  const auto operations = with_builtins.operations();
  CHECK(has(operations, "make_select_rface"));
  CHECK(has(operations, "make_select_redge"));
  CHECK(std::is_sorted(operations.begin(), operations.end()));
  CHECK(ExecutorRegistry::global().contains("make_select_rface"));
}

// ---------------------------------------------------------------------------
// The operation graph (test_graph_lineage.py)
// ---------------------------------------------------------------------------

namespace {

NodePtr add_chain(OperationGraph& graph, int length) {
  NodeSpec root;
  root.op = "root";
  root.params.set("x", 0.0);
  NodePtr node = graph.add_node(std::move(root));
  for (int i = 0; i < length; ++i) {
    NodeSpec step;
    step.op = "step";
    step.params.set("i", i);
    step.inputs = {node};
    node = graph.add_node(std::move(step));
  }
  return node;
}

NodePtr add_diamonds(OperationGraph& graph, int depth) {
  NodeSpec root;
  root.op = "root";
  NodePtr node = graph.add_node(std::move(root));
  for (int i = 0; i < depth; ++i) {
    const auto add = [&](const char* op, std::vector<NodePtr> inputs) {
      NodeSpec spec;
      spec.op = op;
      spec.params.set("i", i);
      spec.inputs = std::move(inputs);
      return graph.add_node(std::move(spec));
    };
    const NodePtr left = add("left", {node});
    const NodePtr right = add("right", {node});
    node = add("join", {left, right});
  }
  return node;
}

}  // namespace

TEST_CASE("upstream_closure visits shared inputs once, inputs first") {
  OperationGraph graph("g");
  const NodePtr top = add_diamonds(graph, 3);
  const auto closure = upstream_closure({top});
  CHECK(closure.size() == 10);
  CHECK(closure.back() == top);
  std::unordered_map<std::string, std::size_t> position;
  for (std::size_t i = 0; i < closure.size(); ++i) position[closure[i]->node_id] = i;
  CHECK(position.size() == 10);
  for (const NodePtr& node : closure) {
    for (const NodePtr& input : node->inputs) CHECK(position[input->node_id] < position[node->node_id]);
  }
}

TEST_CASE("a long chain does not recurse") {
  OperationGraph graph("g");
  const NodePtr tip = add_chain(graph, 20000);
  CHECK(upstream_closure({tip}).size() == 20001);
  CHECK(graph.topological_order().size() == 20001);
  CHECK(graph.is_dag());
}

TEST_CASE("two versions of one node raise StaleLineageError") {
  OperationGraph graph("g");
  NodeSpec spec;
  spec.op = "root";
  spec.params.set("x", 1.0);
  const NodePtr base = graph.add_node(std::move(spec));
  auto stale = std::make_shared<OperationNode>(*base);
  stale->params.set("x", 2.0);
  NodeSpec join_spec;
  join_spec.op = "join";
  join_spec.inputs = {base};
  const NodePtr join = graph.add_node(std::move(join_spec));
  auto other = std::make_shared<OperationNode>(*join);
  other->node_id = "other";
  other->inputs = {stale};
  try {
    upstream_closure({join, other});
    FAIL("expected StaleLineageError");
  } catch (const StaleLineageError& e) {
    CHECK(e.node_id() == base->node_id);
  }
  CHECK(same_node_content(*base, *base));
  CHECK_FALSE(same_node_content(*base, *stale));
}

TEST_CASE("namespaces prefix allocated ids") {
  OperationGraph graph("g", "c1234abcd");
  CHECK(graph.add_node(NodeSpec{.op = "root"})->node_id == "c1234abcd_node_00000001");
  CHECK_THROWS_AS(OperationGraph("g", std::string()), ValueError);
  Session::Options options;
  options.graph_id = "nb";
  options.ns = "c1234abcd";
  Session session(options);
  CHECK(session.allocate_object_id("sketch") == "c1234abcd_sketch_00000001");
  CHECK(session.allocate_object_id("sketch") == "c1234abcd_sketch_00000002");
}

TEST_CASE("adopt inserts a closure and reuses equal nodes") {
  OperationGraph source("g", "ca");
  const NodePtr tip = add_chain(source, 10);
  OperationGraph target("g", "cb");
  CHECK(target.adopt(tip) == tip);
  CHECK(target.node_count() == 11);
  CHECK(target.is_dag());
  auto twin = std::make_shared<OperationNode>(*tip);
  CHECK(target.adopt(twin) == tip);  // equal content: the owned node answers
  CHECK(target.node_count() == 11);

  auto changed = std::make_shared<OperationNode>(*tip);
  changed->params.set("i", -1);
  CHECK_THROWS_AS(target.adopt(changed), StaleLineageError);
  CHECK_THROWS_AS(OperationGraph("other").adopt(tip), ValueError);
}

TEST_CASE("add_node validates ids and inputs") {
  OperationGraph graph("g");
  const NodePtr root = graph.add_node(NodeSpec{.op = "root", .node_id = "a"});
  CHECK_THROWS_AS(graph.add_node(NodeSpec{.op = "root", .node_id = "a"}), ValueError);
  OperationGraph other("h");
  const NodePtr foreign = other.add_node(NodeSpec{.op = "root"});
  CHECK_THROWS_AS(graph.add_node(NodeSpec{.op = "x", .inputs = {foreign}}), ValueError);
  auto copy = std::make_shared<OperationNode>(*root);
  CHECK_THROWS_AS(graph.add_node(NodeSpec{.op = "x", .inputs = {copy}}), ValueError);
}

TEST_CASE("the graph serializes like OperationGraph.to_dict and restores") {
  OperationGraph graph("serial");
  NodeSpec a;
  a.op = "make_box_rsolid";
  a.params.set("width", 1.5);
  a.params.set("depth", 2.0);
  a.tags = {"b", "a"};
  const NodePtr first = graph.add_node(std::move(a));
  NodeSpec b;
  b.op = "make_fillet_rsolid";
  b.params.set("radius", 0.25);
  b.inputs = {first};
  graph.add_node(std::move(b));

  const Value payload = graph.to_value();
  CHECK(payload.find("schema_version")->as_string() == "2.0");
  CHECK(payload.find("graph_id")->as_string() == "serial");
  const auto& nodes = payload.find("nodes")->as_array();
  REQUIRE(nodes.size() == 2);
  CHECK(nodes[0].find("tags")->dump() == "[\"a\",\"b\"]");
  CHECK(nodes[0].find("display")->find("label")->as_string() == "Box Rsolid");
  CHECK(nodes[0].find("display")->find("category")->as_string() == "primitive");
  CHECK(nodes[0].find("display")->find("summary")->as_string() == "width=1.5, depth=2");
  CHECK(nodes[1].find("display")->find("category")->as_string() == "detail");
  CHECK(nodes[1].find("inputs")->dump() == "[\"" + first->node_id + "\"]");
  CHECK(payload.find("edges")->size() == 1);

  const OperationGraph back = OperationGraph::from_value(payload);
  CHECK(back.node_count() == 2);
  CHECK(back.edge_count() == 1);
  CHECK(back.to_value() == payload);
  CHECK_FALSE(graph.to_json().empty());

  Value bad = payload;
  bad.set("schema_version", "1.0");
  CHECK_THROWS_AS(OperationGraph::from_value(bad), ValueError);
  CHECK(OperationGraph::from_value(bad, false).node_count() == 2);
  Value cyclic = payload;
  cyclic.find("nodes")->as_array()[0].set("inputs", Value(Value::Array{Value(nodes[1].find("node_id")->as_string())}));
  CHECK_THROWS_AS(OperationGraph::from_value(cyclic), ValueError);
}

TEST_CASE("topology references can be stamped on every sub-shape") {
  Fixture fx;
  Session::Options options = fx.options();
  options.attach_topology_refs = true;
  Session session(options);
  session.start();
  const Solid box = fx.box(1.0, 2.0, 3.0);
  session.stop();
  const Face face = box.faces().front();
  const Value stamped = face.get_runtime("topo.ref");
  REQUIRE(stamped.is_object());
  CHECK(stamped.find("node_id")->as_string() == node_of(box));
  CHECK(stamped.find("topo_id")->as_string() == face.topo_id());
  CHECK(topo_ref_of(face)->kind == Kind::Face);

  // Without stamping, the same reference is derived from the enumeration's parent links.
  Fixture plain_fx;
  Session plain(plain_fx.options());
  plain.start();
  const Solid other = plain_fx.box(1.0, 2.0, 3.0);
  plain.stop();
  const Face plain_face = other.faces().front();
  CHECK_FALSE(plain_face.get_runtime("topo.ref").is_object());
  const auto derived = topo_ref_of(plain_face);
  REQUIRE(derived);
  CHECK(derived->node_id == node_of(other));
  CHECK(derived->topo_id == plain_face.topo_id());
  CHECK(derived->graph_id == plain.graph().graph_id());
  CHECK_FALSE(topo_ref_of(build_box(1, 1, 1)).has_value());
}

// ---------------------------------------------------------------------------
// OperationBuilder: what an operator author writes
// ---------------------------------------------------------------------------

#include "scad/reactive/record.hpp"

TEST_CASE("OperationBuilder records scalars and registers like an operator would") {
  ExecutorRegistry registry;
  int runs = 0;
  registry.add("op_box", [&runs](const Value& p, const std::vector<OpInput>&, const ScalarValues&) {
    ++runs;
    return std::vector<Shape>{build_box(p.find("size")->as_array()[0].as_double(), p.find("size")->as_array()[1].as_double(), 1.0)};
  });
  const auto op_box = [](const Scalar& x, const Scalar& y) {
    OperationBuilder rec("op_box");
    const double xv = rec.scalar_at("size", 0, x);
    const double yv = rec.scalar_at("size", 1, y);
    rec.param("note", "built");
    Solid out = build_box(xv, yv, 1.0);
    rec.record({out});
    return out;
  };

  // No recorder: it evaluates and records nothing.
  CHECK(op_box(2.0, 3.0).bounding_box().xlen() == doctest::Approx(2.0));
  CHECK_THROWS_AS(op_box(Scalar(HUGE_VAL), 1.0), ValueError);

  Session::Options options;
  options.registry = &registry;
  Session session(options);
  const Sym x = make_var("x", 2.0);
  session.start();
  const Solid box = op_box(x, 3.0);
  session.stop();
  const NodePtr node = session.graph().get_node(node_of(box));
  REQUIRE(node);
  CHECK(node->params.find("size")->dump() == "[2,3]");
  CHECK(node->params.find("note")->as_string() == "built");
  CHECK(node->symbolic.size() == 1);
  CHECK(node->symbolic[0].first == "size[0]");
  CHECK(node->param_exprs.find("size")->dump() == "[{\"expr_id\":\"" + x.expr_id() + "\"},null]");

  session.set_var("x", 7.0);
  CHECK(session.recompute().executed.size() == 1);
  CHECK(runs == 1);
  CHECK(Shape(session.current(box)).bounding_box().xlen() == doctest::Approx(7.0));
}
