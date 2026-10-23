// What the product operators record, and the reactive engine's view of them.
#include "support.hpp"

#include "scad/reactive/expr.hpp"

using namespace scad::product_test;

TEST_CASE("product operations record their parameters and semantic deltas") {
  Recording recording;
  const PartPtr part = part_with_axis("plate");
  AssemblyPtr assembly = with_component(make_assembly_rassembly("fixture"), part, "plate_1", at(1, 0, 0));
  assembly = ground_component_rassembly(*assembly, "plate_1");

  CHECK(recording.ops() == std::vector<std::string>{"make_box_rsolid", "make_part_rpart",
                                                    "make_placement_connector_rconnector", "make_add_connector_rpart",
                                                    "make_assembly_rassembly", "make_add_component_rassembly",
                                                    "make_ground_component_rassembly"});
  const auto& nodes = recording.session.graph().nodes();
  CHECK(nodes[1]->params.find("part_id")->as_string() == "plate");
  CHECK(nodes[1]->params.find("input_refs")->size() == 1);
  CHECK(nodes[5]->params.find("item_kind")->as_string() == "part");
  CHECK(nodes[5]->params.find("placement")->find("origin")->dump() == "[1,0,0]");
  CHECK(recording.session.graph().nodes().size() == 7);
}

TEST_CASE("product ids are unique within a recorded session") {
  const Solid body = make_box_rsolid(1.0, 1.0, 1.0);
  {
    Recording recording;
    make_part_rpart("same_part", body);
    const auto error = failure_of([&] { make_part_rpart("same_part", body); });
    REQUIRE(error);
    CHECK(error->guidance().technical_details.find("duplicate part id in active GraphSession: same_part") !=
          std::string::npos);
    make_material_rmaterial("steel");
    CHECK_THROWS_AS(make_material_rmaterial("steel"), Error);
  }
  // Without a recorder the id may be reused.
  CHECK_NOTHROW(make_part_rpart("same_part", body));
}

TEST_CASE("a geometry connector records the selection it came from") {
  Recording recording;
  const Solid box = make_box_rsolid(1.0, 1.0, 1.0);
  const Face face = box.faces().front();
  const Connector connector = make_face_connector_rconnector("mount", face);
  const auto ops = recording.ops();
  CHECK(ops.back() == "make_face_connector_rconnector");
  CHECK(std::find(ops.begin(), ops.end(), "make_select_rface") != ops.end());
  CHECK(connector.geometry_ref()->source_node_id().has_value());
}

TEST_CASE("a symbolic placement coordinate is kept for the engine") {
  Recording recording;
  const reactive::Sym x = reactive::make_var("x", 4.0);
  const Placement placement = make_placement_rplacement({x.scalar(), Scalar(0.0), Scalar(0.0)});
  CHECK(placement.origin() == Vec3{4, 0, 0});
  const auto& node = *recording.session.graph().nodes().back();
  CHECK(node.symbolic.size() == 1);
  CHECK(node.symbolic.front().first == "origin[0]");
}

TEST_CASE("the executors let a recompute pass through product operations") {
  reactive::ExecutorRegistry registry{false};
  register_geometry_executors(registry);
  register_product_executors(registry);
  reactive::Session::Options options;
  options.registry = &registry;
  reactive::Session session(options);
  session.start();
  const reactive::Sym width = reactive::make_var("w", 2.0);
  const Solid body = make_box_rsolid(width.scalar(), 1.0, 1.0);
  const PartPtr part = make_part_rpart("plate", body);
  (void)part;
  session.stop();

  session.set_var("w", 5.0);
  const reactive::RecomputeReport report = session.recompute();
  CHECK(report.ok());
  CHECK(report.executed.size() == 2);
  CHECK(session.output(session.graph().nodes().front()->node_id).kind() == Kind::Solid);
  CHECK(Solid(session.output(session.graph().nodes().front()->node_id)).volume() == doctest::Approx(5.0));
}

TEST_CASE("every guarded operator has guidance and no name is registered twice") {
  CHECK_NOTHROW(operator_spec("make_part_rpart"));
  CHECK_THROWS_AS(operator_spec("no_such_operator"), reactive::KeyError);
  reactive::ExecutorRegistry registry{false};
  register_product_executors(registry);
  CHECK_THROWS_AS(register_product_executors(registry), ValueError);
  CHECK(registry.operations().size() == 25);
}
