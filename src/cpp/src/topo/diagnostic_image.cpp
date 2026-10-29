#include "scad/topo/diagnostic_image.hpp"

#include <mutex>
#include <utility>

namespace scad {

namespace {

struct Slot {
  std::mutex mutex;
  DiagnosticImageProvider provider;
};

// Leaked: a provider holds Python objects and must not be destroyed after the interpreter has gone.
Slot& slot() {
  static Slot* instance = new Slot();
  return *instance;
}

}  // namespace

void set_diagnostic_image_provider(DiagnosticImageProvider provider) {
  const std::lock_guard<std::mutex> lock(slot().mutex);
  slot().provider = std::move(provider);
}

std::optional<ErrorEvidence> diagnostic_image(const DiagnosticImage& request) {
  DiagnosticImageProvider provider;
  {
    const std::lock_guard<std::mutex> lock(slot().mutex);
    provider = slot().provider;
  }
  if (!provider)
    return std::nullopt;
  try {
    return provider(request);
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

}  // namespace scad
