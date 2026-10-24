"""The operation DAG: ports of the OperationGraph / upstream_closure parts of
test_graph_lineage.py (the pickle / deepcopy parts belong to the notebook cell
cache, which this port does not have)."""

import json

import pytest

import simplecadapi._cpp as scad
from ref import golden


def chain(graph, length):
    node = graph.add_node("root", {"x": 0.0})
    for index in range(length):
        node = graph.add_node("step", {"i": index}, inputs=[node])
    return node


def diamonds(graph, depth):
    """Stack *depth* diamonds; the closure is linear but has 2**depth paths."""
    node = graph.add_node("root")
    for index in range(depth):
        left = graph.add_node("left", {"i": index}, inputs=[node])
        right = graph.add_node("right", {"i": index}, inputs=[node])
        node = graph.add_node("join", {"i": index}, inputs=[left, right])
    return node


def test_postorder_visits_shared_inputs_once():
    graph = scad.OperationGraph("g")
    top = diamonds(graph, 3)
    closure = scad.upstream_closure((top,))
    assert len(closure) == 10 and len({n.node_id for n in closure}) == 10
    assert closure[-1] is top or closure[-1] == top
    position = {n.node_id: i for i, n in enumerate(closure)}
    for node in closure:
        for item in node.inputs:
            assert position[item.node_id] < position[node.node_id]


def test_a_long_chain_needs_no_recursion():
    graph = scad.OperationGraph("g")
    tip = chain(graph, 5000)
    assert len(scad.upstream_closure([tip])) == 5001
    assert len(graph.topological_order()) == 5001


def test_stop_at_cuts_the_walk():
    graph = scad.OperationGraph("g")
    tip = chain(graph, 4)
    cut = graph.nodes[2].node_id
    closure = scad.upstream_closure([tip], stop_at=lambda node: node.node_id == cut)
    assert [n.node_id for n in closure] == [n.node_id for n in graph.nodes[3:]]


def test_namespace_prefixes_node_and_object_ids():
    graph = scad.OperationGraph("g", namespace="c1234abcd")
    assert graph.add_node("root").node_id == "c1234abcd_node_00000001"
    session = scad.GraphSession("nb", namespace="c1234abcd")
    assert session.allocate_object_id("sketch") == "c1234abcd_sketch_00000001"
    with pytest.raises(ValueError):
        scad.OperationGraph("g", namespace="")


def test_adopt_inserts_closure_and_reuses_equal_nodes():
    source = scad.OperationGraph("g", namespace="ca")
    tip = chain(source, 10)
    target = scad.OperationGraph("g", namespace="cb")
    assert target.adopt(tip) == tip
    assert target.node_count == 11 and target.is_dag()
    assert target.adopt(tip).node_id == tip.node_id and target.node_count == 11


def test_adopt_rejects_a_foreign_graph():
    source = scad.OperationGraph("g")
    tip = chain(source, 3)
    with pytest.raises(ValueError):
        scad.OperationGraph("other").adopt(tip)


def test_stale_lineage_is_an_error_with_the_node_id():
    error = scad.StaleLineageError("n1")
    assert isinstance(error, ValueError) and error.node_id == "n1"
    assert "stale lineage" in str(error)


def test_add_node_validates():
    graph = scad.OperationGraph("g")
    graph.add_node("root", node_id="a")
    with pytest.raises(ValueError, match="already exists"):
        graph.add_node("root", node_id="a")
    other = scad.OperationGraph("h")
    foreign = other.add_node("root")
    with pytest.raises(ValueError, match="belongs to graph"):
        graph.add_node("x", inputs=[foreign])


def test_graph_queries():
    graph = scad.OperationGraph("g")
    a = graph.add_node("make_line_redge", {"start": (0, 0, 0), "end": (1, 0, 0)})
    b = graph.add_node("make_line_redge", {"start": (1, 0, 0), "end": (1, 1, 0)})
    wire = graph.add_node("make_wire_from_edges_rwire", {"edge_count": 2}, inputs=[a, b])
    assert graph.node_count == 3 and graph.edge_count == 2
    assert [n.node_id for n in graph.root_nodes()] == [a.node_id, b.node_id]
    assert [n.node_id for n in graph.leaf_nodes()] == [wire.node_id]
    assert graph.upstream_nodes(wire.node_id) == [a.node_id, b.node_id]
    assert graph.downstream_nodes(a.node_id) == [wire.node_id]
    assert graph.edges == {(a.node_id, wire.node_id), (b.node_id, wire.node_id)}
    assert [n.node_id for n in graph.topological_order()] == [a.node_id, b.node_id, wire.node_id]
    assert graph.get_node("missing") is None
    assert wire.inputs == (a, b) and wire.params == {"edge_count": 2}
    assert a.params["start"] == (0, 0, 0)


def test_graph_payload_matches_the_reference():
    snippet = """
        from simplecadapi.topology.model import OperationGraph
        g = OperationGraph("serial")
        a = g.add_node("make_box_rsolid", {"width": 1.5, "depth": 2.0, "tags": ["x", "y"]}, tags={"b", "a"})
        s = g.add_node("make_select_rface", {"target_kind": "face", "source_output_slot": 0}, inputs=[a])
        g.add_node("make_fillet_rsolid", {"radius": 0.25, "selected_edges": [1, 2], "name": "f", "ok": True}, inputs=[a, s])
        g.add_node("translate", {"vector": [1.0, 2.0, 3.0]}, param_exprs={"vector": [{"expr_id": "e1"}, None, None]})
        result = g.to_dict()
    """
    expected = golden("reactive_graph_payload", snippet)
    graph = scad.OperationGraph("serial")
    a = graph.add_node("make_box_rsolid", {"width": 1.5, "depth": 2.0, "tags": ["x", "y"]}, tags={"b", "a"})
    s = graph.add_node("make_select_rface", {"target_kind": "face", "source_output_slot": 0}, inputs=[a])
    graph.add_node("make_fillet_rsolid", {"radius": 0.25, "selected_edges": [1, 2], "name": "f", "ok": True}, inputs=[a, s])
    graph.add_node("translate", {"vector": [1.0, 2.0, 3.0]}, param_exprs={"vector": [{"expr_id": "e1"}, None, None]})
    got = graph.to_dict()
    got.pop("producer_version")
    expected.pop("producer_version")
    assert got == expected
    again = scad.OperationGraph.from_dict(graph.to_dict())
    assert again.to_dict() == graph.to_dict()
    assert scad.OperationGraph.from_json(graph.to_json()).to_dict() == graph.to_dict()


def test_graph_from_dict_validates():
    graph = scad.OperationGraph("g")
    a = graph.add_node("root")
    graph.add_node("child", inputs=[a])
    payload = graph.to_dict()
    for broken in (
        {**payload, "schema_version": "1.0"},
        {**payload, "nodes": 3},
        {**payload, "edges": [["x", "y"]]},
        {**payload, "edges": []},
    ):
        with pytest.raises(ValueError):
            scad.OperationGraph.from_dict(broken)
    assert scad.OperationGraph.from_dict({**payload, "schema_version": "1.0"}, strict=False).node_count == 2


def test_requirements_of_node_equality():
    graph = scad.OperationGraph("g")
    a = graph.add_node("root", {"x": 1.0})
    assert scad.same_node_content(a, a)
    assert a == graph.get_node(a.node_id)
    other = scad.OperationGraph("g")
    assert other.add_node("root", {"x": 2.0}) != a


def test_frame_graph_add_replaces_by_id():
    graph = scad.FrameGraph()
    axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    first = scad.FrameNode("f", (0.0, 0.0, 0.0), *axes)
    second = scad.FrameNode("f", (1.0, 0.0, 0.0), *axes)
    assert graph.add(first) is first
    graph.add(second)
    assert graph.node_count == 1
    assert graph.to_dict()["nodes"][0]["origin"] == (1.0, 0.0, 0.0)
    again = scad.FrameGraph.from_dict(graph.to_dict())
    assert again.to_dict() == graph.to_dict()


def test_frame_graph_payload_matches_the_reference():
    expected = golden(
        "reactive_frame_graph",
        """
        from simplecadapi.params.frame import FrameGraph
        graph = FrameGraph()
        graph.ensure_frame("a", origin=(1.0, 2.0, 3.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 1.0, 0.0),
                           z_axis=(0.0, 0.0, 1.0), metadata={"node_id": "n"})
        graph.ensure_frame("b", origin=(0.0, 0.0, 0.0), x_axis=(0.0, 1.0, 0.0), y_axis=(-1.0, 0.0, 0.0),
                           z_axis=(0.0, 0.0, 1.0), parent_frame_id="a")
        result = graph.to_dict()
        """,
    )
    graph = scad.FrameGraph()
    graph.ensure_frame("a", origin=(1.0, 2.0, 3.0), x_axis=(1.0, 0.0, 0.0), y_axis=(0.0, 1.0, 0.0),
                       z_axis=(0.0, 0.0, 1.0), metadata={"node_id": "n"})
    graph.ensure_frame("b", origin=(0.0, 0.0, 0.0), x_axis=(0.0, 1.0, 0.0), y_axis=(-1.0, 0.0, 0.0),
                       z_axis=(0.0, 0.0, 1.0), parent_frame_id="a")
    assert json.loads(json.dumps(graph.to_dict())) == expected
