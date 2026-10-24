#include "scad/surface/hooks.hpp"

#include <atomic>

#include "scad/core/error.hpp"

namespace scad {

namespace {
std::atomic<ScalarUnitsProbe> g_units_probe{nullptr};
std::atomic<LoftFailureDiagnoser> g_loft_diagnoser{nullptr};
}  // namespace

void set_scalar_units_probe(ScalarUnitsProbe probe) noexcept { g_units_probe.store(probe); }

ScalarUnits scalar_units(const Scalar& value) {
  if (!value.symbolic()) return {};
  const ScalarUnitsProbe probe = g_units_probe.load();
  return probe != nullptr ? probe(value) : ScalarUnits{};
}

void set_loft_failure_diagnoser(LoftFailureDiagnoser diagnoser) noexcept { g_loft_diagnoser.store(diagnoser); }

void diagnose_loft_failure(const std::vector<LoftSection>& sections, std::string_view operation) {
  const LoftFailureDiagnoser diagnoser = g_loft_diagnoser.load();
  if (diagnoser == nullptr) return;
  try {
    diagnoser(sections, operation);
  } catch (const Error&) {
    throw;
  } catch (const std::exception&) {
    // A diagnoser that itself fails explains nothing; the caller applies the generic wrap.
  } catch (...) {
    // Same for non-std exceptions (OpenCASCADE's).
  }
}

}  // namespace scad
