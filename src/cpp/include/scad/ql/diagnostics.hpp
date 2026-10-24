// The text a failed QL query hands back to the agent that wrote it.
//
// A cardinality violation names what matched (hit), what else exists (near_miss),
// whether the matched faces are one logical surface split by a seam, and carries
// one rendered evidence view of the scope.  These builders feed that message;
// none of them throws -- a diagnosis must never mask the failure it describes.
#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/ql/scope.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

// "plane, normal (0, 0, 1), spans y=[-10, 10]" / "circular arc r=5, length 31.42 mm" /
// "(1, 2, 3)": one inventory line.  Falls back to the kind name when the kernel cannot say.
[[nodiscard]] std::string entity_geometry_summary(const Shape& shape);

// Index groups (into `faces`) of two or more faces that lie on one underlying
// quadric surface: a cylinder side OCCT split at a seam is "one logical face".
[[nodiscard]] std::vector<std::vector<std::size_t>> face_logical_groups(const std::vector<Shape>& faces);

// ---- evidence hook -----------------------------------------------------------------
// Rendering belongs to a layer above ql.  Whoever can draw installs a provider; with
// none installed a cardinality error simply carries no evidence.
struct EvidenceRequest {
  const Scope& scope;
  const std::vector<Shape>& matched;
  const std::vector<Shape>& near_misses;  // up to three candidates that did not match
  std::string target_kind;                // "face", "edge", ...
  std::string mode;                       // "exactly" | "at_least" | "at_most"
  std::int64_t expected = 0;
  // ("ql", target_kind, mode, expected, matched count) joined with '|': renders of
  // the same failure are deduplicated on it.
  std::string dedup_key;
};

using EvidenceProvider = std::function<std::vector<ErrorEvidence>(const EvidenceRequest&)>;

// An empty function removes the provider.  Exceptions thrown by a provider are swallowed.
void set_evidence_provider(EvidenceProvider provider);

// Throws the scad::Error of a violated cardinality (`mode` is "exactly", "at_least"
// or "at_most").  If the diagnosis itself fails, a plain ValueError with the bare
// counts is thrown instead.
[[noreturn]] void raise_cardinality_failure(const std::string& target_kind, const std::vector<Shape>& matched,
                                            std::int64_t expected, const std::string& mode, const Scope& scope);

}  // namespace scad::ql
