// Shape serialization: geometry plus semantic state.
#include "doctest.h"

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

#include "scad/core/error.hpp"
#include "scad/io/hash.hpp"
#include "scad/io/json.hpp"
#include "scad/io/serialize.hpp"
#include "scad/topo/shape.hpp"

using namespace scad;
using namespace scad::io;

namespace {

Solid make_box(double x, double y, double z) {
  return Solid(BRepPrimAPI_MakeBox(x, y, z).Solid());
}

TagBinding sample_binding(const std::string& tag, bool explicit_refs = false) {
  TagBinding b;
  b.tag = tag;
  b.policy.mut().producer.kind = TagProducerKind::AutoRule;
  b.policy.mut().producer.rule_id = "test.rule";
  b.policy.mut().producer.rule_version = "1.0";
  if (explicit_refs) {
    b.policy.mut().target.kind = TagTargetKind::ExplicitRefs;
    b.policy.mut().target.refs.push_back(Value::object());
    b.policy.mut().target.refs.back().set("topo_id", "face_1");
  } else {
    b.policy.mut().target.kind = TagTargetKind::SelectionQuery;
    b.policy.mut().target.query_hash = "q123";
    b.policy.mut().target.binding_hash = "b456";
    b.policy.mut().target.selector = Value::object();
    b.policy.mut().target.selector->set("kind", "faces");
  }
  b.policy.mut().propagation.topology = TopologyPropagation::Downward;
  b.policy.mut().propagation.lineage = LineagePolicy::Explicit;
  b.policy.mut().propagation.explicit_derivations = {LineageDerivation::Fragment, LineageDerivation::Merge};
  b.evidence.mut().kind = TagEvidenceKind::GeometryClassification;
  b.evidence.mut().data.set("area", 12.5);
  b.evidence.mut().data.set("count", 3);
  b.evidence.mut().data.set("nested", Value::array());
  b.evidence.mut().data.set("name", "x\xC3\xA9");
  b.policy.mut().scope.node_id = "n1";
  b.policy.mut().scope.output_slot = 2;
  b.certainty = TagCertainty::Proven;
  b.lifecycle = TagLifecycle::Recompute;
  b.binding_id = new_binding_id();
  return b;
}

}  // namespace

TEST_CASE("serialize/deserialize round-trips geometry, tags, bindings, metadata and runtime") {
  Solid solid = make_box(10, 20, 30);
  solid.add_tag("role.body");
  solid.apply_tag("group.all", true);
  solid.set_metadata("name", "bracket");
  Value info = Value::object();
  info.set("mass", 1.25);
  info.set("ids", Value::array());
  info.set("flag", true);
  info.set("none", Value());
  solid.set_metadata("info", info);

  const std::vector<Face> faces = solid.faces();
  Face face = faces[2];
  face.add_binding(sample_binding("feature.hole"));
  TagLineageWitness witness;
  witness.binding = sample_binding("feature.lineage", /*explicit_refs=*/true);
  witness.derivation = LineageDerivation::Fragment;
  witness.source_topo_id = "face_9";
  witness.target_topo_id = "face_2";
  witness.coverage = "partial";
  face.add_lineage_witness(witness);
  face.set_runtime("semantic.lineage.coverage", "complete");
  face.set_runtime("mesh.default", "derived: must not be stored");
  Edge edge = solid.edges()[5];
  edge.set_metadata("geo", info);

  const Bytes bytes = serialize(solid);
  CHECK(bytes.rfind("SCADSHAP", 0) == 0);

  const Shape restored_shape = deserialize(bytes);
  REQUIRE(restored_shape.kind() == Kind::Solid);
  const Solid restored(restored_shape);
  CHECK(restored.volume() == doctest::Approx(6000.0));
  CHECK(restored.faces().size() == 6);
  CHECK(restored.has_tag("role.body", TagScope::Local));
  CHECK(restored.has_tag("group.all", TagScope::Local));
  CHECK(restored.get_metadata("name").as_string() == "bracket");
  CHECK(restored.get_metadata("info") == info);

  const Face face_back = restored.faces()[2];
  CHECK(face_back.topo_id() == face.topo_id());
  REQUIRE(face_back.local_bindings().size() == 1);
  CHECK(python_json_dumps(face_back.local_bindings()[0].to_value()) ==
        python_json_dumps(face.local_bindings()[0].to_value()));
  REQUIRE(face_back.lineage_witnesses().size() == 1);
  CHECK(face_back.lineage_witnesses()[0].coverage == "partial");
  CHECK(python_json_dumps(face_back.lineage_witnesses()[0].to_value()) == python_json_dumps(witness.to_value()));
  CHECK(face_back.get_runtime("semantic.lineage.coverage").as_string() == "complete");
  CHECK(face_back.get_runtime("mesh.default").is_null());
  CHECK(restored.edges()[5].get_metadata("geo") == info);
  CHECK_FALSE(restored.faces()[0].has_tag("feature.hole", TagScope::Local));
  // Entities without state stay clean, and downward tags are inherited like before.
  CHECK(restored.faces()[0].has_tag("group.all", TagScope::Inherited));

  // Byte-stable: serializing the restored shape gives the same bytes.
  CHECK(serialize(restored) == bytes);
}

TEST_CASE("serializing a sub-shape keeps the state of the entities below it") {
  Solid solid = make_box(1, 2, 3);
  Face face = solid.faces()[4];
  face.add_tag("face.marked");
  face.outer_wire().add_tag("wire.marked");
  const Bytes bytes = serialize(face);
  const Shape back_shape = deserialize(bytes);
  REQUIRE(back_shape.kind() == Kind::Face);
  const Face back(back_shape);
  CHECK(back.has_tag("face.marked", TagScope::Local));
  CHECK(back.outer_wire().has_tag("wire.marked", TagScope::Local));
  CHECK(back.area() == doctest::Approx(face.area()));
}

TEST_CASE("serialize a compound of solids with different state") {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  builder.Add(compound, BRepPrimAPI_MakeBox(1, 1, 1).Solid());
  builder.Add(compound, BRepPrimAPI_MakeCylinder(1, 2).Solid());
  Compound shape(compound);
  Solid first = shape.solids()[0];
  first.add_tag("part.first");
  shape.solids()[1].add_tag("part.second");
  const Compound back(deserialize(serialize(shape)));
  REQUIRE(back.solids().size() == 2);
  CHECK(back.solids()[0].has_tag("part.first", TagScope::Local));
  CHECK_FALSE(back.solids()[0].has_tag("part.second", TagScope::Local));
  CHECK(back.solids()[1].has_tag("part.second", TagScope::Local));
}

TEST_CASE("deserialize rejects damaged input with a scad::Error") {
  Solid solid = make_box(1, 1, 1);
  solid.add_tag("role.a");
  const Bytes good = serialize(solid);
  CHECK_THROWS_AS((void)deserialize(""), Error);
  CHECK_THROWS_AS((void)deserialize("not a shape at all, just text of some length........."), Error);
  CHECK_THROWS_AS((void)deserialize(good.substr(0, good.size() - 7)), Error);
  Bytes flipped = good;
  flipped[flipped.size() / 2] = static_cast<char>(flipped[flipped.size() / 2] ^ 0x5A);
  CHECK_THROWS_AS((void)deserialize(flipped), Error);
  Bytes future = good;
  future[9] = 2;  // major version 2
  CHECK_THROWS_AS((void)deserialize(future), Error);
  Bytes flags = good;
  flags[15] = 1;
  CHECK_THROWS_AS((void)deserialize(flags), Error);
  try {
    (void)deserialize("");
    FAIL("expected an error");
  } catch (const Error& e) {
    CHECK(e.operation() == "deserialize_shape");
    CHECK(std::string(e.what()).find("How to fix") != std::string::npos);
  }
}

TEST_CASE("the serialized header is documented big-endian") {
  const Bytes bytes = serialize(make_box(1, 1, 1));
  REQUIRE(bytes.size() > 40);
  CHECK(bytes.substr(0, 8) == "SCADSHAP");
  CHECK(static_cast<unsigned char>(bytes[8]) == 0);
  CHECK(static_cast<unsigned char>(bytes[9]) == 1);   // major 1
  CHECK(static_cast<unsigned char>(bytes[11]) == 0);  // minor 0
  std::uint64_t state_size = 0, brep_size = 0;
  for (int i = 0; i < 8; ++i) {
    state_size = (state_size << 8) | static_cast<unsigned char>(bytes[16 + static_cast<std::size_t>(i)]);
    brep_size = (brep_size << 8) | static_cast<unsigned char>(bytes[24 + static_cast<std::size_t>(i)]);
  }
  CHECK(bytes.size() == 40 + state_size + brep_size);
  CHECK(bytes.substr(40 + state_size, 24) == "\nOpen CASCADE Topology V");
  std::uint32_t crc = 0;
  for (int i = 0; i < 4; ++i)
    crc = (crc << 8) | static_cast<unsigned char>(bytes[32 + static_cast<std::size_t>(i)]);
  CHECK(crc == crc32(std::string_view(bytes).substr(40)));
}
