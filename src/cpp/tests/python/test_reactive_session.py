"""GraphSession and the reactive engine through the Python module, with
synthetic operations (the real operators register their own executors).

Ports of the session parts of test_graph_model_api.py: explicit graph ids,
capture_result, cross-session rejection, deterministic ids."""

import pytest

import simplecadapi._cpp as scad
from simplecadapi._glue.session import GraphSession
from simplecadapi._cpp import _testing


class Model:
    """A box (w, h, d), a second box and a box sized from both of them."""

    def __init__(self):
        self.calls = []
        self.registry = scad.ExecutorRegistry()
        self.registry.add("synth_box", self._box)
        self.registry.add("synth_sum", self._sum)

    def _box(self, params, inputs, scalars):
        self.calls.append("synth_box")
        if params["width"] <= 0:
            raise ValueError("width must be positive")
        return [_testing.box(params["width"], params["height"], params["depth"])]

    def _sum(self, params, inputs, scalars):
        self.calls.append("synth_sum")
        (first, _), (second, _) = inputs
        return [_testing.box(first.get_volume() / 100.0, second.get_volume() / 100.0, params["k"])]

    def session(self, **kwargs):
        return GraphSession(registry=self.registry, **kwargs)

    @staticmethod
    def box(session, width, height, depth):
        shape = _testing.box(scad.evaluate_scalar(width), scad.evaluate_scalar(height), scad.evaluate_scalar(depth))
        session.record("synth_box", {"width": width, "height": height, "depth": depth}, outputs=shape)
        return shape

    @staticmethod
    def total(session, first, second, k):
        shape = _testing.box(first.get_volume() / 100.0, second.get_volume() / 100.0, scad.evaluate_scalar(k))
        session.record("synth_sum", {"k": k}, inputs=[(first, "a"), (second, "b")], outputs=shape)
        return shape


def node_id(shape):
    return shape._get_runtime("graph.node_id")


@pytest.fixture
def model():
    return Model()


def test_recording_through_a_session_context(model):
    w = scad.var("w", 10.0)
    with model.session(graph_id="explicit") as session:
        assert scad.get_active_session() is session
        box = model.box(session, w, 20.0, 30.0)
    assert scad.get_active_session() is None
    assert session.graph.graph_id == "explicit"
    assert session.graph.node_count == 1
    node = session.graph.get_node(node_id(box))
    assert node.op == "synth_box" and node.params == {"width": 10.0, "height": 20.0, "depth": 30.0}
    assert node.param_exprs == {"width": {"expr_id": w.expr_id}}
    assert list(node.symbolic) == ["width"]
    assert [e.expr_id for e in node.expressions] == [w.expr_id]
    assert box._get_runtime("graph.output_slot") == 0
    assert box.get_metadata("graph")["op"] == "synth_box"
    assert session.expression_graph.node_count == 1
    assert session.frame_graph.node_count == 1


def test_edit_and_recompute_only_what_depends_on_it(model):
    w = scad.var("w", 10.0, unit="mm")
    h = scad.var("h", 20.0)
    with model.session() as session:
        first = model.box(session, w, 20.0, 30.0)
        second = model.box(session, 4.0, h, 4.0)
        total = model.total(session, first, second, 2.0)
    a, b, t = node_id(first), node_id(second), node_id(total)
    model.calls.clear()

    assert session.affected_nodes("w") == [a, t]
    assert session.nodes_using("w") == [a]
    assert session.vars_affecting(t) == ["w", "h"]
    assert session.vars_affecting(b) == ["h"]

    session.set_var("w", 20.0)
    assert session.status(a) == "dirty" and session.status(b) == "clean"
    assert session.dirty_nodes() == [a, t]
    report = session.recompute()
    assert report.ok and report.executed == [a, t] and report.changed == [a, t]
    assert model.calls == ["synth_box", "synth_sum"]
    assert session.output(a).get_volume() == pytest.approx(20 * 20 * 30)
    assert session.current(first).get_volume() == pytest.approx(12000.0)
    assert first.get_volume() == pytest.approx(6000.0)  # the held handle is the old build
    assert session.var_value("w") == 20.0 and session.bindings == {"w": 20.0}

    # Moving a slider back is free: the earlier computation is remembered.
    model.calls.clear()
    session.set_var("w", 10.0)
    again = session.recompute()
    assert again.executed == [] and again.memoized == [a, t] and model.calls == []
    assert session.output(a).get_volume() == pytest.approx(6000.0)

    # An edit that is undone before recompute is found equal by digest.
    session.set_var("h", 99.0)
    session.set_var("h", 20.0)
    quiet = session.recompute()
    assert quiet.executed == [] and quiet.memoized == [] and len(quiet.unchanged) == 2
    assert model.calls == []


def test_failures_are_reported_and_block_only_what_follows(model):
    w = scad.var("w", 10.0)
    with model.session() as session:
        first = model.box(session, w, 20.0, 30.0)
        second = model.box(session, 4.0, 4.0, 4.0)
        total = model.total(session, first, second, 2.0)
    session.set_var("w", -1.0)
    report = session.recompute()
    assert not report.ok
    assert [(f.node_id, f.op) for f in report.failed] == [(node_id(first), "synth_box")]
    assert "width must be positive" in report.failed[0].message
    assert report.blocked == [node_id(total)]
    assert session.status(node_id(first)) == "failed"
    assert session.status(node_id(total)) == "blocked"
    assert session.status(node_id(second)) == "clean"
    assert "width must be positive" in session.failure(node_id(first))

    session.set_var("w", 5.0)
    assert session.recompute().ok

    session.set_var("w", -3.0)
    with pytest.raises(scad.SimpleCADError) as caught:
        session.recompute(throw_on_error=True)
    assert caught.value.operation == "synth_box"


def test_variables_validate(model):
    w = scad.var("w", 1.0, unit="in")
    with model.session() as session:
        model.box(session, w, 1.0, 1.0)
    with pytest.raises(KeyError):
        session.set_var("missing", 1.0)
    with pytest.raises(ValueError):
        session.set_var("w", float("inf"))
    with pytest.raises(TypeError):
        session.set_var("w", True)
    session.set_vars({"w": 2.0})
    assert session.var_value("w") == 2.0
    session.reset_var("w")
    assert session.var_value("w") == 1.0 and session.bindings == {}
    spec = session.parameters()[0]
    assert (spec["name"], spec["declared"], spec["unit"], spec["default"]) == ("w", "var", "in", 1.0)
    assert session.has_var("w") and not session.has_var("nope")
    assert [v.name for v in session.vars] == ["w"]
    session.declare_var(scad.var("later", 3.0))
    assert session.has_var("later")


def test_recording_after_an_edit_uses_the_edited_value(model):
    w = scad.var("w", 10.0)
    with model.session() as session:
        model.box(session, w, 1.0, 1.0)
        session.set_var("w", 25.0)
        second = model.box(session, w, 1.0, 1.0)  # evaluate_scalar sees the session's edit
    assert second.get_volume() == pytest.approx(25.0)
    assert session.graph.get_node(node_id(second)).params["width"] == 25.0


def test_missing_executor_is_reported_by_name():
    registry = scad.ExecutorRegistry()
    x = scad.var("x", 1.0)
    session = GraphSession(registry=registry)
    with session:
        session.record("unregistered_op", {"size": x}, outputs=_testing.box(1, 1, 1))
    session.set_var("x", 2.0)
    report = session.recompute()
    assert report.failed[0].op == "unregistered_op"
    assert "no executor is registered" in report.failed[0].message


def test_registry_api():
    registry = scad.ExecutorRegistry(builtins=False)
    assert registry.operations() == []
    registry.add("one", lambda params, inputs, scalars: [])
    with pytest.raises(ValueError):
        registry.add("one", lambda params, inputs, scalars: [])
    registry.replace("one", lambda params, inputs, scalars: [])
    assert registry.contains("one") and registry.remove("one") and not registry.contains("one")
    assert "make_select_rface" in scad.ExecutorRegistry().operations()
    assert scad.global_executor_registry().contains("make_select_rface")


def test_explicit_session_exports_selected_results(model):
    with model.session(graph_id="explicit_session") as session:
        model.box(session, 0.5, 0.5, 0.5)
        result = model.box(session, 1.0, 2.0, 3.0)
        assert session.capture_result(value=result) is result
    assert session.graph.graph_id == "explicit_session"
    assert session.graph.node_count == 2
    assert session.result_node_ids == (node_id(result),)
    assert session.has_explicit_results and session.captured_values == (result,)
    session.clear_results()
    assert not session.has_explicit_results and session.result_node_ids == ()


def test_cross_session_shape_input_is_rejected(model):
    with model.session(graph_id="source") as source:
        foreign = model.box(source, 1.0, 1.0, 1.0)
    with model.session(graph_id="target") as target:
        with pytest.raises(ValueError, match="source.*target"):
            target.record("synth_sum", {"k": 1.0}, inputs=[foreign], outputs=_testing.box(1, 1, 1))
        # a face of the foreign shape is refused the same way
        with pytest.raises(ValueError, match="source.*target"):
            target.record("synth_sum", {"k": 1.0}, inputs=[foreign.faces()[0]], outputs=_testing.box(1, 1, 1))
    assert target.graph.node_count == 0


def test_capture_result_is_atomic_on_failure(model):
    with model.session(graph_id="atomic_capture") as session:
        body = model.box(session, 1.0, 1.0, 1.0)
        with model.session(graph_id="foreign_capture") as other:
            foreign = model.box(other, 2.0, 2.0, 2.0)
        with pytest.raises(ValueError, match="foreign_capture.*atomic_capture"):
            session.capture_result(value=(body, foreign))
        assert not session.has_explicit_results and session.result_node_ids == ()
        with pytest.raises(ValueError, match="at least one graph-backed"):
            session.capture_result(value=_testing.box(1, 1, 1))


def test_capture_result_walks_containers_and_dataclasses(model):
    import dataclasses

    @dataclasses.dataclass
    class ResultValue:
        body: object

    with model.session() as session:
        body = model.box(session, 1.0, 2.0, 3.0)
        session.capture_result(value={"k": [ResultValue(body=body)]})
    assert session.result_node_ids == (node_id(body),)


def test_repeated_sessions_have_deterministic_graph_payloads(model):
    def build():
        with model.session(graph_id="deterministic_session") as session:
            w = scad.var("w", 5.0)
            a = model.box(session, w, 2.0, 3.0)
            b = model.box(session, 1.0, 2.0, 3.0)
            model.total(session, a, b, 2.0)
        payload = session.graph.to_json()
        return payload, session.expression_graph.to_dict()

    assert build() == build()


def test_suspend_and_isolation(model):
    with model.session() as session:
        model.box(session, 1.0, 1.0, 1.0)
        with scad.suspend_graph_recording():
            assert scad.get_active_session() is session
            assert scad.record_operation_if_active("synth_box", {"width": 1.0}, _testing.box(1, 1, 1)) is None
        with scad.isolated_recording():
            assert scad.get_active_session() is None
        node = scad.record_operation_if_active("synth_box", {"width": 2.0, "height": 1.0, "depth": 1.0}, _testing.box(2, 1, 1))
        assert node is not None and node.op == "synth_box"
    assert session.graph.node_count == 2
    assert scad.record_operation_if_active("synth_box", {}, None) is None


def test_session_must_not_start_twice(model):
    session = model.session()
    session.start()
    with pytest.raises(RuntimeError, match="already active"):
        session.start()
    session.stop()
    assert scad.get_active_session() is None


def test_a_session_without_shared_lineage_refuses_another_sessions_values():
    with GraphSession(graph_id="notebook", namespace="c1") as first:
        box = scad.make_box_rsolid(1, 2, 3)
    with GraphSession(graph_id="notebook", namespace="c2"):
        with pytest.raises(ValueError, match="not owned by active graph"):
            scad.translate_shape(box, (1, 0, 0))
    assert first.graph.node_count == 1


def test_shared_lineage_adopts_the_node_a_value_came_from():
    with GraphSession(graph_id="notebook", namespace="c1", shared_lineage=True):
        box = scad.make_box_rsolid(1, 2, 3)
        moved_once = scad.translate_shape(box, (1, 0, 0))
    with GraphSession(graph_id="notebook", namespace="c2", shared_lineage=True) as second:
        moved_twice = scad.translate_shape(moved_once, (1, 0, 0))
    ops = [node.op for node in second.graph.topological_order()]
    assert ops[0] == "make_box_rsolid" and len(ops) == 3
    assert second.graph.get_node(second.graph.nodes[-1].node_id).inputs[0].node_id == moved_once._get_runtime("graph.node_id")
    assert moved_twice._get_runtime("graph.node_id") == second.graph.nodes[-1].node_id
    other_graph = GraphSession(graph_id="elsewhere", shared_lineage=True)
    with other_graph:
        with pytest.raises(ValueError, match="from graph 'notebook'"):
            scad.translate_shape(moved_twice, (1, 0, 0))


def test_a_restored_graph_keeps_its_deltas_and_builds_on_registered_nodes():
    with GraphSession(graph_id="nb", namespace="c1", shared_lineage=True) as upstream:
        box = scad.make_box_rsolid(1, 2, 3)
    with GraphSession(graph_id="nb", namespace="c2", shared_lineage=True) as cell:
        scad.cut_rsolid(box, scad.make_cylinder_rsolid(0.2, 10, bottom_face_center=(0, 0, -1)))
    own = [n for n in cell.graph.to_dict()["nodes"] if n["node_id"].startswith("c2_")]
    assert own and any(n.get("topo_delta") for n in own)
    scad.forget_graph_nodes("nb")
    scad.register_graph_nodes(upstream.graph)  # the upstream cell is restored first
    restored = scad.OperationGraph.from_dict(
        {"graph_id": "nb", "nodes": own, "edges": []}, strict=False
    )
    assert restored.node_count == cell.graph.node_count
    for node in restored.nodes:
        original = cell.graph.get_node(node.node_id)
        assert node.op == original.op
        assert [i.node_id for i in node.inputs] == [i.node_id for i in original.inputs]
        assert node.semantic_delta is None or node.semantic_delta.created == original.semantic_delta.created
        assert (node.topo_delta is None) == (original.topo_delta is None)


def test_a_value_operation_takes_the_nodes_of_its_value_arguments():
    with GraphSession(graph_id="g") as session:
        first = scad.make_box_rsolid(1, 1, 1)
        node = session.graph.nodes[0]
        session._expect_value_op([node], True)
        part = scad.make_part_rpart("p", first)
    made = session.last_node
    assert made.op == "make_part_rpart" and made.output_count == 1
    assert [i.node_id for i in made.inputs] == [node.node_id]
    assert session.last_node is not None and part.part_id == "p"
    session._clear_value_op()


def test_the_source_provider_stamps_each_node():
    calls = []

    def where():
        calls.append(1)
        return {"line": 7}

    with GraphSession(graph_id="g", source_provider=where) as session:
        scad.make_box_rsolid(1, 1, 1)
    assert session.graph.nodes[0].source == {"line": 7} and calls


def test_a_picked_face_follows_its_source(model):
    registry = scad.ExecutorRegistry()
    calls = []
    registry.add("synth_box", model._box)

    def feature(params, inputs, scalars):
        calls.append("feature")
        face = inputs[0][0]
        return [_testing.box(face.get_center().x * 2.0, 1.0, 1.0)]

    registry.add("synth_feature", feature)
    w = scad.var("w", 10.0)
    session = GraphSession(registry=registry)
    with session:
        box = model.box(session, w, 20.0, 30.0)
        face = max(box.faces(), key=lambda f: f.get_center().x)  # the +x face
        out = _testing.box(face.get_center().x * 2.0, 1.0, 1.0)
        session.record("synth_feature", {}, inputs=[face], outputs=out)
    ops = [n.op for n in session.graph.nodes]
    assert ops == ["synth_box", "make_select_rface", "synth_feature"]
    session.set_var("w", 40.0)
    assert session.recompute().ok
    assert session.current(face).get_center().x == pytest.approx(40.0)
    assert session.current(out).get_volume() == pytest.approx(80.0 * 1.0 * 1.0)
    assert calls == ["feature"]


def test_a_tag_assignment_node_owns_its_binding():
    with GraphSession(graph_id="g") as session:
        box = scad.make_box_rsolid(1, 2, 3)
        face = box.faces()[0]  # an enumerated face knows its container, hence its recorded reference
        scad.apply_tag_rselection(box, [face], "mytag")
    node = next(n for n in session.graph.nodes if n.op == "apply_tag_rselection")
    assert node.node_id.startswith("n_")
    assert node.params["tag_binding"]["producer"]["node_id"] == node.node_id
    refs = node.params["tag_binding"]["evidence"]["selected_refs"]
    assert refs[0]["graph_id"] == "g" and refs[0]["kind"] == "FACE" and refs[0]["node_id"]


def test_the_recorded_delta_names_the_entities_of_its_node():
    with GraphSession(graph_id="g") as session:
        box = scad.make_box_rsolid(1, 2, 3)
        scad.cut_rsolid(box, scad.make_cylinder_rsolid(0.2, 10, bottom_face_center=(0, 0, -1)))
    payload = session.graph.to_dict()
    for node in payload["nodes"]:
        delta = node.get("topo_delta")
        if not delta:
            continue
        refs = [entry["ref"] for entry in delta["roles"]] + [entry["ref"] for entry in delta["entries"]]
        assert refs
        for ref in refs:
            assert not ref["graph_id"].startswith("g_") and not ref["node_id"].startswith("n_")
            assert ref["kind"] == ref["kind"].upper()
            assert ref["topo_id"].startswith(ref["kind"].lower() + "_" + ref["kind"].lower() + "_")
        assert all(entry["event"] == entry["event"].upper() for entry in delta["entries"])
