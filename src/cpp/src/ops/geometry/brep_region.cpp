#include "scad/ops/geometry/brep_region.hpp"

#include <filesystem>

#include "internal.hpp"
#include "scad/io/brep_region.hpp"
#include "scad/topo/tag_factories.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

// A manifest member, null when absent.
Value member(const Value& object, std::string_view key) {
  const Value* found = object.find(key);
  return found != nullptr ? *found : Value();
}

std::string python_str(const Value& value) {
  return value.is_string() ? value.as_string() : value.is_null() ? "None" : value.dump();
}

TagBinding provenance_binding(const Value& evidence, TopologyPropagation topology, const std::string& scope,
                              const std::string& artifact_sha256, const std::string& subject) {
  TagBinding binding;
  binding.tag = "provenance.exact_transcription";
  binding.policy.mut().producer = TagProducer{.kind = TagProducerKind::ImportedSidecar};
  binding.policy.mut().target = TagTarget{.kind = TagTargetKind::ScopeRoot};
  binding.policy.mut().propagation =
      TagPropagation{.topology = topology, .lineage = LineagePolicy::ContinuationFragment};
  binding.evidence = TagEvidence{.kind = TagEvidenceKind::ImportedSidecar, .data = evidence};
  binding.certainty = TagCertainty::Asserted;
  binding.lifecycle = TagLifecycle::Snapshot;
  binding.binding_id =
      "tag_binding_" + uuid5_url_hex("simplecad.brep_region." + scope + "|" + artifact_sha256 + "|" + subject);
  return binding;
}

// `_attach_brep_region_provenance`: the region's source on the root and on every face.
template <class T>
void attach_provenance(T& shape, const Value& manifest, const std::string& artifact_sha256) {
  const Value source = member(manifest, "source");
  const Value region = member(manifest, "region");
  const Value face_ids = member(region, "source_face_ids");

  Value evidence = Value::object();
  evidence.set("artifact_sha256", artifact_sha256);
  evidence.set("profile", member(manifest, "profile"));
  evidence.set("source_sha256", member(source, "content_hash"));
  evidence.set("source_name", member(source, "name"));
  evidence.set("source_face_ids", face_ids);
  evidence.set("construction", "exact_transcription");
  evidence.set("topology_origin", "retained");
  evidence.set("runtime_dependency", "embedded_target_derived");

  shape.add_binding(provenance_binding(evidence, TopologyPropagation::Downward, "root", artifact_sha256,
                                       python_str(member(region, "kind"))));

  const std::size_t id_count = face_ids.is_array() ? face_ids.as_array().size() : 0;
  std::size_t index = 0;
  for (Face& face : shape.faces()) {
    Value face_evidence = evidence;
    face_evidence.set("source_face_id", index < id_count ? face_ids.as_array()[index] : Value());
    face.set_metadata("provenance", face_evidence);
    face.add_binding(provenance_binding(face_evidence, TopologyPropagation::Local, "face", artifact_sha256,
                                        python_str(*face_evidence.find("source_face_id"))));
    face.set_runtime("semantic.lineage.coverage", Value("complete"));
    ++index;
  }
}

template <class T>
T load_region(std::string_view path, std::string_view sha256, const OptionalString& tag_prefix, const char* op,
              io::RegionRootKind kind) {
  const bool replaying = graph_recording();
  const std::string source_path = io::checked_region_path(path, replaying);
  const std::optional<std::filesystem::path> replay_root =
      replaying ? std::optional<std::filesystem::path>(std::filesystem::current_path()) : std::nullopt;
  io::RegionFile file = io::read_artifact(io::path_from_utf8(source_path), sha256, kind, replay_root);

  const std::string root_kind(io::to_string(kind));
  T shape(file.shape);
  shape.add_tag("imported");
  shape.add_tag("sidecar");
  shape.add_tag(root_kind);
  OptionalString prefix;
  if (tag_prefix) {
    prefix = normalize_tag(*tag_prefix, true);
    shape.apply_tag(*prefix + "." + root_kind, false);
  }
  shape.set_metadata(
      "brep_region",
      Value(Value::Object{{"artifact_sha256", Value(file.sha256)},
                          {"profile", member(file.manifest, "profile")},
                          {"provenance", member(file.manifest, "provenance")},
                          {"source_face_ids", member(member(file.manifest, "region"), "source_face_ids")}}));
  attach_provenance(shape, file.manifest, file.sha256);

  return finalize_primitive_with(std::move(shape), op, [&] {
    return OpParams(op, {"imported", root_kind, "sidecar"})
        .text("path", source_path)
        .text("sha256", file.sha256)
        .optional_text("tag_prefix", prefix)
        .take();
  });
}

}  // namespace

Solid load_brep_region_rsolid(std::string_view path, std::string_view sha256, const OptionalString& tag_prefix) {
  static constexpr const char* kOp = "load_brep_region_rsolid";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to load the BREP region snapshot.",
      {"The snapshot path does not exist or is not readable.",
       "The supplied SHA-256 does not match the snapshot bytes.",
       "The snapshot is corrupt, unsupported, invalid, or not one solid."},
      {"Create the snapshot with copy_step_region_rpath(...).", "Pass the SHA-256 of the complete .scadbrep file.",
       "Keep the sidecar at the same path when replaying model JSON."}};
  return guarded(kSpec, [&] { return load_region<Solid>(path, sha256, tag_prefix, kOp, io::RegionRootKind::Solid); });
}

Shell load_brep_region_rshell(std::string_view path, std::string_view sha256, const OptionalString& tag_prefix) {
  static constexpr const char* kOp = "load_brep_region_rshell";
  static const ErrorSpec kSpec{kOp,
                               "Failed to load the BREP face-region snapshot.",
                               {"The snapshot path or SHA-256 is incorrect.",
                                "The snapshot is corrupt, unsupported, invalid, or not one Shell."},
                               {"Create a face-region snapshot with copy_step_region_rpath(..., face_ids=[...]).",
                                "Pass the SHA-256 of the complete .scadbrep file."}};
  return guarded(kSpec, [&] { return load_region<Shell>(path, sha256, tag_prefix, kOp, io::RegionRootKind::Shell); });
}

}  // namespace scad
