#include <cmath>
#include <map>
#include <set>

#include "scad/product/solver.hpp"

namespace scad::product {

namespace {

const char* const kReportFields[] = {"solved", "grounded_component_ids", "solved_component_ids", "unsolved_component_ids",
                                     "residuals"};
const char* const kResidualFields[] = {"constraint_id", "translation_error", "angular_error_degrees", "within_tolerance"};

template <std::size_t N>
bool has_exactly(const Value& object, const char* const (&fields)[N]) {
  if (!object.is_object() || object.size() != N) return false;
  for (const char* field : fields) {
    if (object.find(field) == nullptr) return false;
  }
  return true;
}

// The ids of a report list: nullopt unless it is a list of distinct strings.
std::optional<std::set<std::string>> id_set(const Value& list) {
  if (!list.is_array()) return std::nullopt;
  std::set<std::string> ids;
  for (const Value& item : list.as_array()) {
    if (!item.is_string() || !ids.insert(item.as_string()).second) return std::nullopt;
  }
  return ids;
}

std::optional<std::map<std::string, const Value*>> residuals_by_id(const Value& list) {
  if (!list.is_array()) return std::nullopt;
  std::map<std::string, const Value*> out;
  for (const Value& item : list.as_array()) {
    if (!has_exactly(item, kResidualFields)) return std::nullopt;
    const Value& id = *item.find("constraint_id");
    if (!id.is_string() || !out.emplace(id.as_string(), &item).second) return std::nullopt;
  }
  return out;
}

bool close(const Value& a, const Value& b, double tolerance) {
  return a.is_number() && b.is_number() && std::abs(a.as_double() - b.as_double()) <= tolerance;
}

}  // namespace

bool constraint_reports_match(const Value& actual, const Value& expected) {
  if (!has_exactly(actual, kReportFields) || !has_exactly(expected, kReportFields)) return false;
  if (*actual.find("solved") != *expected.find("solved")) return false;
  for (const char* field : {"grounded_component_ids", "solved_component_ids", "unsolved_component_ids"}) {
    const auto a = id_set(*actual.find(field));
    const auto b = id_set(*expected.find(field));
    if (!a || !b || *a != *b) return false;
  }
  const auto a = residuals_by_id(*actual.find("residuals"));
  const auto b = residuals_by_id(*expected.find("residuals"));
  if (!a || !b || a->size() != b->size()) return false;
  for (const auto& [id, left] : *a) {
    const auto right = b->find(id);
    if (right == b->end()) return false;
    const Value& l = *left;
    const Value& r = *right->second;
    if (*l.find("within_tolerance") != *r.find("within_tolerance")) return false;
    if (!close(*l.find("translation_error"), *r.find("translation_error"), kPlacementTolerance)) return false;
    if (!close(*l.find("angular_error_degrees"), *r.find("angular_error_degrees"), kAngleToleranceDegrees)) return false;
  }
  return true;
}

}  // namespace scad::product
