#include "scad/ops/features/support.hpp"

#include <BRepCheck_Analyzer.hxx>
#include <TopoDS_Solid.hxx>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/reactive/geo_selection.hpp"
#include "scad/reactive/session.hpp"
#include "scad/semantic/finalize.hpp"

namespace scad {

double evaluate_finite(const Scalar& scalar) {
  const double number = scalar.value();
  if (!std::isfinite(number))
    throw ValueError("value must be finite");
  return number;
}

// ---------------------------------------------------------------------------
// FeatureRecord
// ---------------------------------------------------------------------------
FeatureRecord::FeatureRecord(std::string_view op) : recording_(current_recorder() != nullptr) {
  record_.op = std::string(op);
  if (recording_)
    record_.params = Value::object();
}

double FeatureRecord::scalar(std::string_view name, const Scalar& value) {
  const double number = evaluate_finite(value);
  if (recording_) {
    record_.params.set(std::string(name), number);
    if (value.symbolic())
      record_.symbolic.emplace_back(std::string(name), value);
  }
  return number;
}

Vec3 FeatureRecord::point(std::string_view name, const Scalar3& value) {
  const std::string path(name);
  double xyz[3];
  Value numbers = Value::tuple();
  for (std::size_t i = 0; i < 3; ++i) {
    const std::string item = path + "[" + std::to_string(i) + "]";
    xyz[i] = evaluate_finite(value[i]);
    if (!recording_)
      continue;
    numbers.push_back(xyz[i]);
    if (value[i].symbolic())
      record_.symbolic.emplace_back(item, value[i]);
  }
  if (recording_)
    record_.params.set(path, std::move(numbers));
  return {xyz[0], xyz[1], xyz[2]};
}

std::vector<std::vector<double>> FeatureRecord::matrix(std::string_view name,
                                                       const std::vector<std::vector<Scalar>>& value) {
  const std::string path(name);
  std::vector<std::vector<double>> numbers;
  Value rows = Value::array();
  for (std::size_t i = 0; i < value.size(); ++i) {
    std::vector<double>& row = numbers.emplace_back();
    Value recorded = Value::array();
    for (std::size_t j = 0; j < value[i].size(); ++j) {
      const std::string item = path + "[" + std::to_string(i) + "][" + std::to_string(j) + "]";
      row.push_back(evaluate_finite(value[i][j]));
      if (!recording_)
        continue;
      recorded.push_back(row.back());
      if (value[i][j].symbolic())
        record_.symbolic.emplace_back(item, value[i][j]);
    }
    if (recording_)
      rows.push_back(std::move(recorded));
  }
  if (recording_)
    record_.params.set(path, std::move(rows));
  return numbers;
}

FeatureRecord& FeatureRecord::param(std::string_view name, Value value) {
  if (recording_)
    record_.params.set(std::string(name), std::move(value));
  return *this;
}

FeatureRecord& FeatureRecord::input(const Shape& shape, std::string role) {
  record_.inputs.push_back(OpInput{shape, std::move(role)});
  return *this;
}

OpRecord FeatureRecord::take() && {
  return std::move(record_);
}

PickParams capture_picks(const Shape& source, const std::vector<Shape>& picked, const std::vector<Shape>& candidates,
                         bool refs_first) {
  PickParams out;
  if (current_recorder() == nullptr)
    return out;
  reactive::Session* session = reactive::Session::active_session();
  if (refs_first)
    out.refs = reactive::serialize_shape_refs(picked);
  if (session != nullptr)
    out.node_ids = session->ensure_selection_nodes(source, picked);
  if (!refs_first)
    out.refs = reactive::serialize_shape_refs(picked);
  if (out.node_ids.empty())
    out.indices = reactive::serialize_selection_indices(picked, candidates);
  return out;
}

void PickParams::apply_refs(FeatureRecord& rec, std::string_view refs_key) const {
  rec.param(refs_key, refs);
}

void PickParams::apply_ids(FeatureRecord& rec, std::string_view ids_key, std::string_view indices_key) const {
  if (!node_ids.empty()) {
    Value ids = Value::array();
    for (const std::string& id : node_ids)
      ids.push_back(id);
    rec.param(ids_key, std::move(ids));
  } else if (!indices_key.empty()) {
    rec.param(indices_key, indices);
  }
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
bool recording_session_active() {
  return reactive::Session::active_session() != nullptr || current_recorder() != nullptr;
}

std::string_view to_string(TrackingPolicy policy) noexcept {
  return policy == TrackingPolicy::Graph ? "graph" : "full";
}

TrackingPolicy resolve_tracking_policy(std::string_view requested) {
  if (current_tracking_policy() == TrackingPolicy::Graph)
    return TrackingPolicy::Graph;
  std::string lowered(requested);
  std::transform(lowered.begin(), lowered.end(), lowered.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (lowered == "full")
    return TrackingPolicy::Full;
  if (lowered == "graph")
    return TrackingPolicy::Graph;
  throw ValueError("'" + std::string(requested) + "' is not a valid TrackingPolicy");
}

Vec3 finite_vector(const Scalar3& value, std::string_view name) {
  const Vec3 point{value[0].value(), value[1].value(), value[2].value()};
  // The Python SDK's scalar evaluation rejects a non-finite number before the vector is checked.
  (void)name;
  if (!point.is_finite())
    throw ValueError("value must be finite");
  return point;
}

void inherit_metadata(Shape& target, std::initializer_list<const Shape*> sources) {
  for (const Shape* source : sources) {
    const Value& metadata = source->metadata();
    if (!metadata.is_object())
      continue;
    for (const auto& [key, value] : metadata.as_object())
      target.set_metadata(key, value);
  }
}

std::string general_format(double value, int digits) {
  char buffer[64];
  std::snprintf(buffer, sizeof buffer, "%.*g", digits, value);
  return buffer;
}

std::string python_float_repr(double value) {
  if (std::isnan(value))
    return "nan";
  if (std::isinf(value))
    return value > 0 ? "inf" : "-inf";
  if (value == 0.0)
    return std::signbit(value) ? "-0.0" : "0.0";

  // The fewest significant digits that read back as the same double.
  char text[48];
  for (int digits = 1; digits <= 17; ++digits) {
    std::snprintf(text, sizeof text, "%.*e", digits - 1, value);
    if (std::strtod(text, nullptr) == value)
      break;
  }
  std::string scientific = text;  // "-d.ddde+XX"
  const bool negative = scientific.front() == '-';
  if (negative)
    scientific.erase(0, 1);
  const std::size_t e = scientific.find('e');
  std::string digits = scientific.substr(0, e);
  digits.erase(std::remove(digits.begin(), digits.end(), '.'), digits.end());
  while (digits.size() > 1 && digits.back() == '0')
    digits.pop_back();
  const int exponent = std::atoi(scientific.c_str() + e + 1);
  const int decimal_point = exponent + 1;  // position of the point within `digits`
  const int count = static_cast<int>(digits.size());

  std::string out = negative ? "-" : "";
  if (decimal_point > -4 && decimal_point <= 16) {
    if (decimal_point <= 0) {
      out += "0." + std::string(static_cast<std::size_t>(-decimal_point), '0') + digits;
    } else if (decimal_point >= count) {
      out += digits + std::string(static_cast<std::size_t>(decimal_point - count), '0') + ".0";
    } else {
      out += digits.substr(0, static_cast<std::size_t>(decimal_point)) + "." +
             digits.substr(static_cast<std::size_t>(decimal_point));
    }
    return out;
  }
  out += digits.substr(0, 1);
  if (count > 1)
    out += "." + digits.substr(1);
  char tail[16];
  std::snprintf(tail, sizeof tail, "e%c%02d", exponent < 0 ? '-' : '+', std::abs(exponent));
  return out + tail;
}

// ---------------------------------------------------------------------------
// _finish
// ---------------------------------------------------------------------------
Solid finish_solid(const Shape& source, const TopoDS_Shape& built, OpRecord record) {
  const std::vector<TopoDS_Solid> solids = kernel::solids_of(built);
  if (solids.size() != 1) {
    throw ValueError(record.op + " must produce exactly one solid, got " + std::to_string(solids.size()));
  }
  TopoDS_Solid solid = solids.front();
  // A kernel that hands back an inside-out solid has a negative volume.
  if (kernel::volume(solid) < 0)
    solid.Reverse();
  if (!occt_guard([&] { return BRepCheck_Analyzer(solid).IsValid(); })) {
    throw ValueError(record.op + " produced invalid geometry");
  }

  Solid result(solid);
  inherit_metadata(result, {&source});
  // These builders do not yet provide a complete face-history channel.
  attach_lineage_from_source(source, result, LineageDerivation::Continuation, record.op, "partial");
  if (Recorder* recorder = current_recorder()) {
    std::vector<Shape> inputs;
    for (const OpInput& input : record.inputs)
      inputs.push_back(input.shape);
    if (auto refs = recorder->input_refs(inputs))
      record.params.set("input_refs", std::move(*refs));
  }
  record_operation(record, {result});
  return result;
}

}  // namespace scad
