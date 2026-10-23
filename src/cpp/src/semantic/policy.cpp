#include "scad/semantic/tracked_result.hpp"

namespace scad {

namespace {
thread_local TrackingPolicy g_policy = TrackingPolicy::Full;
}

TrackingPolicy current_tracking_policy() noexcept { return g_policy; }

TrackingPolicyScope::TrackingPolicyScope(TrackingPolicy policy) noexcept : previous_(g_policy) { g_policy = policy; }
TrackingPolicyScope::~TrackingPolicyScope() { g_policy = previous_; }

}  // namespace scad
