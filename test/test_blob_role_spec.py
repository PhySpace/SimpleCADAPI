"""H3 contract tests: blob-ref spec symmetry and semantic-domain rejection."""
import unittest
from pathlib import Path

import simplecadapi as scad
import simplecadapi.product.packages as pp
from simplecadapi.artifacts.canonical import (
    canonical_bytes,
    content_hash,
    parse_canonical_json,
    sha256_bytes,
)
from simplecadapi.product.packages import ProductPackageError
from simplecadapi.scene.archive import canonical_zip_bytes


def _build_part_package() -> scad.ProductPackage:
    material = scad.make_material_rmaterial(
        material_id="spec_steel", density=7.85e-6, density_unit="kg/mm^3"
    )

    @scad.part(id="spec_bar", project_root=Path(__file__).parent)
    def build_bar() -> scad.Part:
        body = scad.make_box_rsolid(width=8.0, height=4.0, depth=2.0)
        part = scad.make_part_rpart("spec_bar", body)
        part = scad.assign_material_rpart(part=part, material=material)
        return part

    return scad.build_product_package(build_bar(), include_scene=False)


class TestBlobRoleSpec(unittest.TestCase):
    def test_runtime_and_manifest_ref_paths_agree(self):
        package = _build_part_package()
        runtime_paths = sorted(
            str(ref["path"])
            for ref in pp._definition_refs(package.root_definition)
        )
        definition_manifest = parse_canonical_json(
            package.objects[package.root_path]
        )
        self.assertIsInstance(definition_manifest, dict)
        manifest_paths = sorted(
            str(ref["path"])
            for ref in pp._definition_refs_from_manifest(
                "single_solid", definition_manifest
            )
        )
        self.assertEqual(runtime_paths, manifest_paths)
        self.assertEqual(len(runtime_paths), 4)

    def test_package_rejects_ref_outside_semantic_domain(self):
        package = _build_part_package()
        old_definition_path = package.root_path
        definition_manifest = dict(
            parse_canonical_json(package.objects[old_definition_path])
        )
        definition_section = dict(definition_manifest["definition"])
        feature_ref = dict(definition_section["feature_graph_ref"])
        feature_ref["path"] = "smuggled/evil.bin"
        definition_section["feature_graph_ref"] = feature_ref
        definition_manifest["definition"] = definition_section
        definition_manifest["content_hash"] = content_hash(definition_manifest)
        definition_payload = canonical_bytes(definition_manifest)
        definition_digest = definition_manifest["content_hash"].removeprefix(
            "sha256:"
        )
        new_definition_path = f"definitions/part/{definition_digest}.json"

        manifest = dict(package.manifest)
        definition_record = dict(manifest["definitions"][0])
        definition_record.update(
            {
                "path": new_definition_path,
                "content_hash": definition_manifest["content_hash"],
                "sha256": sha256_bytes(definition_payload),
                "byte_length": len(definition_payload),
            }
        )
        manifest["definitions"] = [definition_record]
        root_record = dict(manifest["root"])
        root_record.update(
            {
                "path": new_definition_path,
                "content_hash": definition_manifest["content_hash"],
            }
        )
        manifest["root"] = root_record
        manifest["content_hash"] = content_hash(
            {
                key: value
                for key, value in manifest.items()
                if key != "content_hash"
            },
            omit=(),
        )

        objects = dict(package.objects)
        del objects[old_definition_path]
        objects[new_definition_path] = definition_payload
        payload = canonical_zip_bytes(
            {"package.json": canonical_bytes(manifest), **objects},
            manifest_name="package.json",
        )
        with self.assertRaises(ProductPackageError) as ctx:
            scad.read_product_package(payload)
        self.assertIn("semantic domain", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
