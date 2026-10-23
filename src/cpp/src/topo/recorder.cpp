#include "scad/topo/recorder.hpp"

namespace scad {

namespace {
thread_local Recorder* g_current = nullptr;
}

Recorder* current_recorder() noexcept { return g_current; }

RecorderScope::RecorderScope(Recorder* recorder) noexcept : previous_(g_current) { g_current = recorder; }
RecorderScope::~RecorderScope() { g_current = previous_; }

}  // namespace scad
