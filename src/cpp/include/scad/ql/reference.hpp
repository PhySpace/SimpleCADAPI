// References as predicates: ql.ref(r) keeps the entities a stable element reference resolves to.
//
//   ql::faces().where(ql::ref(record)).resolve(part)
//
// `record` is the data of a reference (simplecadapi.ref.ElementRef.to_dict(): feature, op, occurrence, kind,
// role or topo id, piece, guard, naming version); it is stored in the predicate as it is, so a selector holding a
// reference serialises and replays like any other.  What the record resolves to depends on the shape the selector
// is resolved against (the reference walks that shape's recorded history), so the predicate asks the reference
// resolver once per reference per query run, with the scope, and keeps the candidates that are among the answer.
//
// The resolver is installed by the SDK (simplecadapi.ref: the history walk, the choice of a piece of a split and
// the errors for a split or lost reference are its); without one, or outside a selector resolved against one
// shape, a reference predicate is an error, never "nothing matched".
#pragma once

#include <functional>
#include <vector>

#include "scad/core/value.hpp"
#include "scad/ql/predicate.hpp"
#include "scad/topo/shape.hpp"

namespace scad::ql {

// resolver(scope, record) -> the entities of `scope` the reference names; throws when it names none or several.
using ReferenceResolver = std::function<std::vector<Shape>(const Shape& scope, const Value& record)>;

// Install (or, with an empty function, remove) the reference resolver.
void set_reference_resolver(ReferenceResolver resolver);

// The entities `record` names in `scope` (ValueError when no resolver is installed).
[[nodiscard]] std::vector<Shape> resolve_reference(const Shape& scope, const Value& record);

// The predicate: candidates among the entities the reference resolves to in the selector's scope.
[[nodiscard]] Predicate ref(Value record);

}  // namespace scad::ql
