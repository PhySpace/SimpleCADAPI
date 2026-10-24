// Internals shared by the src/reactive translation units.  Not installed.
#pragma once

#include <TopAbs_ShapeEnum.hxx>

#include <optional>
#include <string>
#include <string_view>

#include "scad/core/value.hpp"
#include "scad/reactive/registry.hpp"
#include "scad/reactive/session.hpp"
#include "scad/topo/shape.hpp"

namespace scad::reactive::detail {

// "make_select_rface" for Kind::Face, ...; empty for a compound.
std::string selection_op_name(Kind kind);

// (index, count) of `picked` among the sub-shapes of its kind in `source` (nullopt when it is not one).
std::optional<std::pair<std::int64_t, std::int64_t>> index_in_source(const Shape& source, const Shape& picked);

TopAbs_ShapeEnum topabs_of(Kind kind);
std::string kind_token(const Shape& shape);

// The sub-shape of `source` a geo_exact selector describes.  `index` is where it was found when
// the source had `count` sub-shapes of the kind (a recompute: take the same one); otherwise the
// one that scores best against the selector (_geo_selector_score).  ValueError when there is none.
Shape resolve_geo_selector(const Shape& source, const Value& selector,
                           const std::optional<std::pair<std::int64_t, std::int64_t>>& index = std::nullopt);

// The index encoded in a topo id ("face_3" -> 3).
std::optional<std::size_t> topo_index(std::string_view topo_id);

// Registers the executors of the selection operations.
void register_selection_executors(ExecutorRegistry& registry);

// The thread's active session pointer (Session::active_session), settable by
// the classes that scope it.
Session*& active_session_slot() noexcept;

}  // namespace scad::reactive::detail
