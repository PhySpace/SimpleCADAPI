import unittest
from unittest import mock

import simplecadapi as scad
from simplecadapi import operators as operations, tagging


class TestTaggingRefactor(unittest.TestCase):
    def test_tag_validation(self):
        self.assertTrue(tagging.is_normalized_tag("geom.primitive.box"))
        self.assertTrue(tagging.is_normalized_tag("face.top"))
        self.assertFalse(tagging.is_normalized_tag("Face.Top"))
        self.assertFalse(tagging.is_normalized_tag("size: 2x3x4"))

    def test_apply_tag_does_not_infer_propagation_from_prefix(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        scad.apply_tag(box, "role.mounting_surface")

        self.assertIn("role.mounting_surface", box._list_tags("local"))
        self.assertFalse(
            any(
                "role.mounting_surface" in face._list_tags("effective")
                for face in box._iter_faces()
            )
        )

    def test_explicit_downward_propagation_is_computed_not_copied(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        binding = box._apply_user_tag(
            "role.mounting_surface", topology_propagation="downward"
        )
        face = box.get_faces(0)
        edge = face.get_edges(0)

        self.assertEqual(
            face._list_tags("local"), ["face.box.back", "face.left"]
        )
        self.assertNotIn("role.mounting_surface", face._list_tags("local"))
        self.assertIn("role.mounting_surface", face._list_tags("inherited"))
        self.assertIn("role.mounting_surface", edge._list_tags("inherited"))
        self.assertNotIn(binding, face._tag_bindings)
        self.assertIn("role.mounting_surface", face._tags)

    def test_effective_includes_lineage(self):
        # Tags are a view over history: what the lineage carries is part of the effective tags.
        source = scad.make_point_rvertex(0.0, 0.0, 0.0)
        result = scad.make_point_rvertex(1.0, 0.0, 0.0)
        binding = source._apply_user_tag("role.datum")
        result._add_tag_lineage(
            binding,
            derivation="continuation",
            source_topo_id=source.topo_id,
            evidence=tagging.TagEvidence(
                "topology_change", {"change_ids": ["change_1"]}
            ),
        )
        result._set_runtime("semantic.lineage.coverage", "complete")

        self.assertIn("role.datum", result._list_tags("effective"))
        self.assertEqual(result._list_tags("lineage"), ["role.datum"])

    def test_lineage_requires_complete_history(self):
        vertex = scad.make_point_rvertex(0.0, 0.0, 0.0)

        with self.assertRaises(tagging.UnsupportedQueryCapabilityError):
            vertex._list_tags("lineage")

        vertex._set_runtime("semantic.lineage.coverage", "partial")
        with self.assertRaises(tagging.UnsupportedQueryCapabilityError):
            vertex._list_tags("lineage")

    def test_default_lineage_policy_rejects_boundary(self):
        source = scad.make_point_rvertex(0.0, 0.0, 0.0)
        result = scad.make_point_rvertex(1.0, 0.0, 0.0)
        binding = source._apply_user_tag("role.datum")
        result._add_tag_lineage(
            binding,
            derivation="boundary",
            source_topo_id=source.topo_id,
            evidence=tagging.TagEvidence("topology_change"),
        )
        result._set_runtime("semantic.lineage.coverage", "complete")

        self.assertEqual(result._list_tags("lineage"), [])

    def test_lineage_continues_across_multiple_proven_hops(self):
        source = scad.make_point_rvertex(0.0, 0.0, 0.0)
        scad.apply_tag(source, "role.datum")

        first = scad.translate_shape(source, (1.0, 0.0, 0.0))
        second = scad.translate_shape(first, (1.0, 0.0, 0.0))

        self.assertIn("role.datum", scad.list_tags(second, "effective"))
        self.assertEqual(scad.list_tags(second, "lineage"), ["role.datum"])

    def test_disallowed_lineage_does_not_seed_later_continuation(self):
        source = scad.make_point_rvertex(0.0, 0.0, 0.0)
        intermediate = scad.make_point_rvertex(1.0, 0.0, 0.0)
        binding = source._apply_user_tag("role.datum")
        intermediate._add_tag_lineage(
            binding,
            derivation="boundary",
            source_topo_id=source.topo_id,
            evidence=tagging.TagEvidence("topology_change"),
        )
        intermediate._set_runtime("semantic.lineage.coverage", "complete")

        result = scad.translate_shape(intermediate, (1.0, 0.0, 0.0))

        self.assertEqual(scad.list_tags(result, "lineage"), [])

    def test_lineage_explanation_filters_disallowed_witnesses(self):
        source = scad.make_point_rvertex(0.0, 0.0, 0.0)
        result = scad.make_point_rvertex(1.0, 0.0, 0.0)
        binding = source._apply_user_tag("role.datum")
        result._add_tag_lineage(
            binding,
            derivation="boundary",
            source_topo_id=source.topo_id,
            evidence=tagging.TagEvidence("topology_change"),
        )
        result._set_runtime("semantic.lineage.coverage", "complete")

        self.assertEqual(scad.explain_tag(result, "role.datum", "lineage"), [])

    def test_lineage_witness_roundtrip_preserves_source_binding(self):
        binding = tagging.user_tag_binding("role.datum", node_id="node_source")
        witness = tagging.TagLineageWitness(
            binding=binding,
            derivation="fragment",
            source_topo_id="face_source",
            target_topo_id="face_target",
            evidence=tagging.TagEvidence(
                "topology_change", {"change_ids": ["change_1"]}
            ),
        )

        self.assertEqual(
            tagging.TagLineageWitness.from_dict(witness.to_dict()), witness
        )

    def test_binding_schema_roundtrip_is_strict(self):
        binding = tagging.TagBinding(
            binding_id="tag_binding_mounting_surface",
            tag="role.mounting_surface",
            producer=tagging.TagProducer("user_operation", node_id="node_tag"),
            scope=tagging.TagBindingScope("node_body", 0),
            target=tagging.TagTarget(
                "selection_query",
                query_hash="sha256:query",
                binding_hash="sha256:binding",
            ),
            propagation=tagging.TagPropagation(
                topology="local", lineage="continuation_fragment"
            ),
            evidence=tagging.TagEvidence(
                "query_execution",
                {
                    "execution_hash": "sha256:execution",
                    "selected_refs": [],
                },
            ),
        )

        payload = binding.to_dict()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(tagging.TagBinding.from_dict(payload), binding)

        malformed = dict(payload)
        malformed["unknown"] = True
        with self.assertRaises(tagging.TagValidationError):
            tagging.TagBinding.from_dict(malformed)

        missing_scope = dict(payload)
        missing_scope.pop("scope")
        with self.assertRaises(tagging.TagValidationError):
            tagging.TagBinding.from_dict(missing_scope)

    def test_same_token_dedupes_but_explanation_preserves_producers(self):
        vertex = scad.make_point_rvertex(0.0, 0.0, 0.0)
        user_binding = tagging.user_tag_binding(
            "role.datum", node_id="node_user"
        )
        auto_binding = tagging.TagBinding(
            tag="role.datum",
            producer=tagging.TagProducer(
                "auto_rule",
                rule_id="simplecad.test.datum",
                rule_version="1.0",
            ),
            evidence=tagging.TagEvidence("geometry_classification"),
            certainty="proven",
            lifecycle="recompute",
        )
        vertex._add_tag_binding(user_binding)
        vertex._add_tag_binding(auto_binding)

        self.assertEqual(vertex._list_tags("local"), ["role.datum"])
        explanations = vertex._explain_tag("role.datum", "local")
        self.assertEqual(len(explanations), 2)
        self.assertEqual(
            {item["producer"]["kind"] for item in explanations},
            {"user_operation", "auto_rule"},
        )

        self.assertEqual(vertex._remove_tag("role.datum"), 1)
        self.assertEqual(vertex._list_tags("local"), ["role.datum"])
        self.assertEqual(
            vertex._explain_tag("role.datum", "local")[0]["producer"]["kind"],
            "auto_rule",
        )

    def test_internal_and_legacy_bindings_are_not_user_assertions(self):
        vertex = scad.make_point_rvertex(0.0, 0.0, 0.0)
        vertex._add_tag("internal.marker")
        internal = vertex._explain_tag("internal.marker", "local")[0]
        self.assertEqual(internal["producer"]["kind"], "auto_rule")

        vertex._tags = {"legacy.marker"}
        legacy = vertex._explain_tag("legacy.marker", "effective")[0]
        self.assertEqual(legacy["producer"]["kind"], "legacy_import")
        self.assertEqual(legacy["attachment"], "effective_legacy")
        with self.assertRaises(tagging.UnsupportedQueryCapabilityError):
            vertex._list_tags("local")

    def test_tagging_public_surface_is_functional_and_sorted(self):
        vertex = scad.make_point_rvertex(0.0, 0.0, 0.0)

        scad.apply_tag(vertex, "role.zeta")
        scad.apply_tag(vertex, "role.alpha")

        self.assertEqual(scad.list_tags(vertex), ["role.alpha", "role.zeta"])
        for member_name in ("add_tag", "apply_tag", "get_tags", "has_tag", "remove_tag"):
            self.assertFalse(hasattr(vertex, member_name))
        self.assertFalse(hasattr(scad, "set_tag"))

    def test_apply_tag_mutates_without_cloning_semantic_topology(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)

        with mock.patch.object(
            operations,
            "clone_semantic_shape_view",
            wraps=operations.clone_semantic_shape_view,
        ) as clone:
            tagged = scad.apply_tag(box, "role.structure")

        self.assertIs(tagged, box)
        self.assertEqual(clone.call_count, 0)
        self.assertIn("role.structure", scad.list_tags(box, scope="local"))

    def test_apply_tag_rselection_keeps_independent_clone(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)

        with mock.patch.object(
            operations,
            "clone_semantic_shape_view",
            wraps=operations.clone_semantic_shape_view,
        ) as clone:
            tagged = scad.apply_tag_rselection(
                box,
                scad.ql.solids().exactly(1),
                "role.structure",
            )

        self.assertIsNot(tagged, box)
        self.assertEqual(clone.call_count, 1)
        self.assertNotIn("role.structure", scad.list_tags(box, scope="local"))
        self.assertIn("role.structure", scad.list_tags(tagged, scope="local"))

    def test_apply_tag_rselection_and_explain_tag_public_surface(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        source_face = box.get_faces(0)

        tagged = scad.apply_tag_rselection(
            box,
            [source_face],
            "role.mounting_surface",
            topology_propagation=scad.TopologyPropagation.LOCAL,
            lineage_policy=scad.LineagePolicy.CONTINUATION_FRAGMENT,
        )
        tagged_face = next(
            face for face in tagged._iter_faces() if face.topo_id == source_face.topo_id
        )

        self.assertIn(
            "role.mounting_surface",
            scad.list_tags(tagged_face, scad.TagScope.LOCAL),
        )
        explanation = scad.explain_tag(
            tagged_face, "role.mounting_surface", scad.TagScope.LOCAL
        )
        self.assertEqual(len(explanation), 1)
        self.assertEqual(explanation[0]["producer"]["kind"], "user_operation")

    def test_anchor_resolution_candidate_priority(self):
        candidates = tagging.resolve_anchor_tag_candidates("mounting_surface")

        self.assertEqual(candidates[0], "role.mounting_surface")
        self.assertEqual(candidates[1], "anchor.mounting_surface")
        self.assertIn("face.mounting_surface", candidates)
        self.assertEqual(candidates[-1], "mounting_surface")

    def test_new_primitive_tags_are_normalized_and_geo_metadata_carries_values(self):
        box = scad.make_box_rsolid(1.0, 2.0, 3.0)

        box_tags = scad.list_tags(box)
        self.assertEqual(box_tags, sorted(box_tags))
        self.assertTrue(all(tagging.is_normalized_tag(tag) for tag in box_tags))
        self.assertFalse(any(tag.isdigit() for tag in box_tags))
        self.assertFalse(any(":" in tag or " " in tag for tag in box_tags))
        self.assertEqual(box.get_metadata("geo")["size"], {"x": 1.0, "y": 2.0, "z": 3.0})

    def test_wire_edge_indices_live_in_geo_metadata_not_tags(self):
        wire = scad.make_rectangle_rwire(1.0, 1.0)
        edges = wire._iter_edges()

        self.assertTrue(edges)
        self.assertFalse(any(tag.isdigit() for edge in edges for tag in scad.list_tags(edge)))
        self.assertTrue(all(edge.get_metadata("geo")["edge_index"] >= 0 for edge in edges))

    def test_anchor_resolution_prefers_role_over_anchor_and_topology_tags(self):
        candidates = tagging.resolve_anchor_tag_candidates("datum")

        self.assertLess(candidates.index("role.datum"), candidates.index("anchor.datum"))
        self.assertLess(candidates.index("anchor.datum"), candidates.index("face.datum"))


class TestAutoTagFacesNamespaces(unittest.TestCase):
    def test_box_faces_have_new_tags(self):
        box = scad.make_box_rsolid(1.0, 1.0, 1.0)
        box.auto_tag_faces("box")
        faces = box._iter_faces()
        self.assertTrue(any("face.top" in scad.list_tags(face) for face in faces))
        self.assertTrue(any("face.bottom" in scad.list_tags(face) for face in faces))

    def test_cylinder_faces_have_new_tags(self):
        cylinder = scad.make_cylinder_rsolid(1.0, 2.0)
        cylinder.auto_tag_faces("cylinder")
        faces = cylinder._iter_faces()
        self.assertTrue(any("face.top" in scad.list_tags(face) for face in faces))
        self.assertTrue(any("face.bottom" in scad.list_tags(face) for face in faces))
        self.assertTrue(any("face.side" in scad.list_tags(face) for face in faces))

    def test_sphere_faces_have_new_tags(self):
        sphere = scad.make_sphere_rsolid(1.0)
        sphere.auto_tag_faces("sphere")
        faces = sphere._iter_faces()
        self.assertEqual(len(faces), 1)
        self.assertIn("face.surface", scad.list_tags(faces[0]))


if __name__ == "__main__":
    unittest.main()
