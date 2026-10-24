// The history engine behind tracked_* (src/semantic/tracking_*.cpp).  Private:
// not installed, not for other areas.
//
// Shape of the work, per operation:
//   1. build the result with the OCCT algorithm;
//   2. `query_*_history` asks the algorithm what happened to each input
//      sub-shape and appends one Witness per fact;  `operation_role` /
//      `roles_from_history` collect role evidence;
//   3. `DeltaBuilder::finish` turns the witnesses into the TopoDelta and the
//      `delta_entries` table.
// A Witness is the typed form of the Python dicts that tracking.py passes
// between those steps; the key order of the Values built from it matches them.
#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <BRepBuilderAPI_MakeShape.hxx>
#include <BRepTools_History.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/kernel/membership.hpp"
#include "scad/semantic/tracked_result.hpp"
#include "scad/topo/delta.hpp"
#include "scad/topo/shape.hpp"

namespace scad::tracking {

// ---- identities ------------------------------------------------------------

// The temporary graph/node ids one operation's refs carry (Python `_make_id`).
struct OperationIds {
  std::string graph_id;
  std::string node_id;
};
OperationIds new_operation_ids();

// "FACE": TopoKind.name, which the Python witness dicts use.
std::string_view kind_token(Kind kind) noexcept;
// The kind of `shape`, or `fallback` for a type the delta model has no kind for.
Kind kind_of_shape(const TopoDS_Shape& shape, Kind fallback) noexcept;

// ---- witnesses -------------------------------------------------------------

// One kernel-history fact about one shape.  `topo_id` is the output shape's id
// (the input's own id for preserved and deleted); `input_topo_id` the input
// sub-shape it descends from.  coverage is always "complete", status "proven":
// everything here is read straight off the kernel.
struct Witness {
  std::string topo_id;
  TopoEvent event = TopoEvent::Preserved;
  Kind kind = Kind::Face;         // of topo_id
  Kind source_kind = Kind::Face;  // of input_topo_id
  std::string origin_role;        // "body" / "tool" / "profile" ... (never empty)
  std::string input_topo_id;
  std::string_view derivation;    // continuation | fragment | boundary | replacement
  std::string_view result_role;   // "" = none
  bool project_source_tags = false;
};

// Kernel-backed output role of a result entity.
struct RoleWitness {
  std::string topo_id;
  Kind kind = Kind::Face;
  std::string role;
  std::optional<std::string> origin_role;
  std::optional<std::string> input_topo_id;
  std::optional<Kind> source_kind;
  std::string_view evidence_method;
};

// ---- history sources -------------------------------------------------------

// What the kernel remembers about an operation, whichever object holds it.
class HistorySource {
 public:
  virtual ~HistorySource() = default;
  virtual bool is_deleted(const TopoDS_Shape& shape) = 0;
  // The lists are valid until the next call on this source (builders reuse one
  // buffer for Modified and Generated), so callers copy what they keep.
  virtual const TopTools_ListOfShape& modified(const TopoDS_Shape& shape) = 0;
  virtual const TopTools_ListOfShape& generated(const TopoDS_Shape& shape) = 0;
};

// A finished BRepBuilderAPI_MakeShape (prism, fillet, transform, ...).
class BuilderHistory final : public HistorySource {
 public:
  explicit BuilderHistory(BRepBuilderAPI_MakeShape& builder) noexcept : builder_(builder) {}
  bool is_deleted(const TopoDS_Shape& s) override { return builder_.IsDeleted(s); }
  const TopTools_ListOfShape& modified(const TopoDS_Shape& s) override { return builder_.Modified(s); }
  const TopTools_ListOfShape& generated(const TopoDS_Shape& s) override { return builder_.Generated(s); }

 private:
  BRepBuilderAPI_MakeShape& builder_;
};

// A retained BRepTools_History (booleans, N-ary union).
class RetainedHistory final : public HistorySource {
 public:
  explicit RetainedHistory(const BRepTools_History& history) noexcept : history_(history) {}
  bool is_deleted(const TopoDS_Shape& s) override { return history_.IsRemoved(s); }
  const TopTools_ListOfShape& modified(const TopoDS_Shape& s) override { return history_.Modified(s); }
  const TopTools_ListOfShape& generated(const TopoDS_Shape& s) override { return history_.Generated(s); }

 private:
  const BRepTools_History& history_;
};

// ---- querying --------------------------------------------------------------

// Everything `_query_exact_history` takes besides the builder and the shapes.
struct QuerySpec {
  std::string_view origin_role;
  Kind kind = Kind::Face;                  // of the inputs
  kernel::SubShapeIndex* result = nullptr; // only facts that land in the result; null = no filter
  std::string_view modified_derivation = "fragment";
  std::string_view generated_derivation = "boundary";
  // result_role applies to every event; the specific ones override it.
  std::string_view result_role;
  std::string_view preserved_role;
  std::string_view modified_role;
  std::string_view generated_role;
  bool project_source_tags = false;
};

// False under TrackingPolicy::Graph: nothing below is then computed.  Check it
// before building inputs for a query that would be thrown away.
bool history_wanted() noexcept;

// What became of each of `inputs` (distinct shapes, in the order given).
void query_history(HistorySource& history, const TopTools_IndexedMapOfShape& inputs, const QuerySpec& spec,
                   std::vector<Witness>& out);
// The same for every sub-shape of `type` in `input` (_query_history).
void query_sub_shape_history(HistorySource& history, const TopoDS_Shape& input, TopAbs_ShapeEnum type,
                             const QuerySpec& spec, std::vector<Witness>& out);
// The same for an arbitrary list; duplicates (IsSame) are queried once.
void query_list_history(HistorySource& history, const std::vector<TopoDS_Shape>& inputs, const QuerySpec& spec,
                        std::vector<Witness>& out);

// ---- roles -----------------------------------------------------------------

// `_operation_role`: nullopt unless `candidate` is part of the result.
std::optional<RoleWitness> operation_role(kernel::SubShapeIndex& result, const TopoDS_Shape& candidate,
                                          std::string_view role, std::string_view evidence_method,
                                          std::optional<std::string_view> origin_role = std::nullopt);
// Append operation_role(...) when it exists.
void add_operation_role(std::vector<RoleWitness>& roles, kernel::SubShapeIndex& result,
                        const TopoDS_Shape& candidate, std::string_view role, std::string_view evidence_method,
                        std::optional<std::string_view> origin_role = std::nullopt);
// `_roles_from_history`: one role per witness that has a result_role, from
// witnesses[begin..].
void add_roles_from_history(std::vector<RoleWitness>& roles, const std::vector<Witness>& witnesses,
                            std::string_view evidence_method, std::size_t begin = 0);

// ---- assembling ------------------------------------------------------------

struct Finished {
  TopoDelta delta;
  DeltaEntries delta_entries;
};

// Accumulates one operation's facts and builds its delta.
class DeltaBuilder {
 public:
  DeltaBuilder() : ids_(new_operation_ids()) {}

  std::vector<Witness> witnesses;
  std::vector<RoleWitness> roles;
  std::vector<std::string> section_edge_ids;  // kernel ids of EDGE section edges, in order
  // fillet/chamfer aggregate their edge facts and roles first and only then add
  // the face facts that came before them (witnesses[0, yielding_prefix)), which
  // lose to the edge facts when both describe the same id.
  std::size_t yielding_prefix = 0;

  const OperationIds& ids() const noexcept { return ids_; }

  // Build the delta.  Consumes the builder.
  Finished finish() &&;

 private:
  OperationIds ids_;
};

// The usual ending of a tracked_* function.
inline TrackedResult to_result(const Shape& shape, DeltaBuilder&& builder) {
  Finished finished = std::move(builder).finish();
  return TrackedResult{shape, std::move(finished.delta), std::move(finished.delta_entries)};
}

}  // namespace scad::tracking
