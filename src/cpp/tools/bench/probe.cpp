// Allocation and time probe for the semantic layers (macOS malloc zone statistics).
//
//   probe sizes
//   probe box|bare_box|fillet|cut|box_edges  N      retained heap bytes and blocks per object
//   probe time box|bare_box|fillet|cut|box_edges N  microseconds per object, nothing retained
//
// Retained bytes come from malloc_zone_statistics, so they count everything the process
// allocates through malloc (OCCT included) and exclude page-level fragmentation.
#include <cxxabi.h>
#include <dlfcn.h>
#include <execinfo.h>
#include <malloc/malloc.h>
#include <sys/mman.h>

#include <algorithm>
#include <cstdint>

#include <BRepAlgoAPI_Cut.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <cstring>
#include <optional>
#include <string>
#include <vector>

#include "scad/reactive/session.hpp"
#include "scad/ops/features/features.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/ql/ql.hpp"
#include "../../src/topo/internal.hpp"

using namespace scad;

namespace {
struct Heap { std::size_t bytes, blocks; };
Heap heap() {
  malloc_statistics_t s{};
  malloc_zone_statistics(nullptr, &s);
  return {s.size_in_use, s.blocks_in_use};
}
using Clock = std::chrono::steady_clock;


// ---- live-bytes-by-call-stack profile (macOS malloc_logger) ----------------------------------
extern "C" {
typedef void(malloc_logger_t)(uint32_t, uintptr_t, uintptr_t, uintptr_t, uintptr_t, uint32_t);
extern malloc_logger_t* malloc_logger;
}
namespace prof {
constexpr int kDepth = 14;
struct Stack { std::uint64_t hash; void* frames[kDepth]; int n; long bytes; long blocks; };
struct Live { std::uintptr_t ptr; std::uint32_t stack; std::uint32_t size; };
constexpr std::size_t kLive = 1u << 23, kStacks = 1u << 16;
Live* live; Stack* stacks; std::size_t nstacks = 0;
long current = 0, peak = 0;
thread_local bool busy = false;
void* map(std::size_t bytes) { return mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0); }
std::uint32_t stack_slot(void** f, int n) {
  std::uint64_t h = 1469598103934665603ull;
  for (int i = 0; i < n; ++i) h = (h ^ reinterpret_cast<std::uintptr_t>(f[i])) * 1099511628211ull;
  std::size_t i = h % kStacks;
  while (stacks[i].n != 0 && stacks[i].hash != h) i = (i + 1) % kStacks;
  if (stacks[i].n == 0) { stacks[i].hash = h; stacks[i].n = n; std::copy(f, f + n, stacks[i].frames); ++nstacks; }
  return static_cast<std::uint32_t>(i);
}
void put(std::uintptr_t ptr, std::uint32_t stack, std::uint32_t size) {
  std::size_t i = (ptr >> 4) * 11400714819323198485ull >> 41 & (kLive - 1);
  while (live[i].ptr != 0 && live[i].ptr != 1) i = (i + 1) & (kLive - 1);
  live[i] = {ptr, stack, size};
}
void drop(std::uintptr_t ptr) {
  std::size_t i = (ptr >> 4) * 11400714819323198485ull >> 41 & (kLive - 1);
  while (live[i].ptr != 0) {
    if (live[i].ptr == ptr) { current -= live[i].size; stacks[live[i].stack].bytes -= live[i].size; --stacks[live[i].stack].blocks; live[i].ptr = 1; return; }
    i = (i + 1) & (kLive - 1);
  }
}
void log(uint32_t type, uintptr_t, uintptr_t a2, uintptr_t, uintptr_t result, uint32_t) {
  if (busy) return;
  busy = true;
  if (type & 4) drop(a2);                    // dealloc (free, or the old half of a realloc)
  if ((type & 2) && result != 0) {            // alloc
    void* f[kDepth + 3];
    const int n = backtrace(f, kDepth + 3);
    const std::uint32_t slot = stack_slot(f + 3, n > 3 ? n - 3 : 0);
    const auto size = static_cast<std::uint32_t>(malloc_size(reinterpret_cast<void*>(result)));
    stacks[slot].bytes += size; ++stacks[slot].blocks; current += size; if (current > peak) peak = current;
    put(result, slot, size);
  }
  busy = false;
}
void start() { busy = false; { void* f[4]; backtrace(f, 4); } live = static_cast<Live*>(map(kLive * sizeof(Live))); stacks = static_cast<Stack*>(map(kStacks * sizeof(Stack))); malloc_logger = log; }
void stop() { malloc_logger = nullptr; }
std::string name(void* addr) {
  Dl_info info{};
  if (!dladdr(addr, &info) || !info.dli_sname) return "?";
  int status = 0;
  char* d = abi::__cxa_demangle(info.dli_sname, nullptr, nullptr, &status);
  std::string out = status == 0 && d ? d : info.dli_sname;
  std::free(d);
  if (out.size() > 90) out.resize(90);
  return out;
}
void report(int top, int per_stack, int n_objects) {
  std::vector<Stack*> all;
  for (std::size_t i = 0; i < kStacks; ++i) if (stacks[i].n != 0 && stacks[i].bytes > 0) all.push_back(&stacks[i]);
  std::sort(all.begin(), all.end(), [](Stack* a, Stack* b) { return a->bytes > b->bytes; });
  long total = 0; for (Stack* s : all) total += s->bytes;
  std::printf("live total %.1f KB/object over %d objects, %zu stacks\n", double(total) / n_objects / 1024.0, n_objects, all.size());
  for (int k = 0; k < top && k < static_cast<int>(all.size()); ++k) {
    const Stack& s = *all[static_cast<std::size_t>(k)];
    std::printf("%6.2f KB/obj %6.1f blk/obj\n", double(s.bytes) / n_objects / 1024.0, double(s.blocks) / n_objects);
    for (int i = 0; i < per_stack && i < s.n; ++i) std::printf("      %s\n", name(s.frames[i]).c_str());
  }
}
}  // namespace prof

std::vector<std::shared_ptr<void>> g_keep;

template <class T>
void keep(T&& v) { g_keep.push_back(std::make_shared<std::decay_t<T>>(std::forward<T>(v))); }

void make(const std::string& what_in) {
  std::string what = what_in;
  if (what.size() > 4 && what.compare(what.size() - 4, 4, "_rec") == 0) what.resize(what.size() - 4);  // recorded: same op
  if (what == "bare_box") {
    keep(BRepPrimAPI_MakeBox(10, 20, 30).Shape());
  } else if (what == "bare_fillet") {
    TopoDS_Shape box = BRepPrimAPI_MakeBox(10, 20, 30).Shape();
    BRepFilletAPI_MakeFillet mk(box);
    for (TopExp_Explorer ex(box, TopAbs_EDGE); ex.More(); ex.Next()) mk.Add(1.0, TopoDS::Edge(ex.Current()));
    keep(mk.Shape());
  } else if (what == "bare_cut") {
    BRepAlgoAPI_Cut cut(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), BRepPrimAPI_MakeCylinder(4.0, 40.0).Shape());
    keep(cut.Shape());
  } else if (what == "box") {
    keep(make_box_rsolid(10, 20, 30));
  } else if (what == "box_edges") {
    Solid s = make_box_rsolid(10, 20, 30);
    for (const Face& f : s.faces()) { (void)f.edges(); (void)f.list_tags(); }
    keep(std::move(s));
  } else if (what == "fillet") {
    keep(fillet_rsolid(make_box_rsolid(10, 20, 30), ql::edges(), 1.0));
  } else if (what == "cut") {
    keep(cut_rsolid({make_box_rsolid(10, 20, 30), make_cylinder_rsolid(4.0, 40.0)}));
  }
}
}  // namespace

int main(int argc, char** argv) {
  if (argc >= 2 && !std::strcmp(argv[1], "sizes")) {
    std::printf("TagBinding %zu TagProducer %zu TagBindingScope %zu TagTarget %zu TagPropagation %zu TagEvidence %zu\n",
                sizeof(TagBinding), sizeof(TagProducer), sizeof(TagBindingScope), sizeof(TagTarget),
                sizeof(TagPropagation), sizeof(TagEvidence));
    std::printf("Value %zu SemanticState %zu Entity %zu Shape %zu TagLineageWitness %zu std::string %zu\n", sizeof(Value),
                sizeof(SemanticState), sizeof(Entity), sizeof(Shape), sizeof(TagLineageWitness), sizeof(std::string));
    return 0;
  }
  if (argc >= 2 && !std::strcmp(argv[1], "vol")) {
    TopoDS_Shape box = BRepPrimAPI_MakeBox(10, 20, 30).Shape();
    BRepFilletAPI_MakeFillet mk(box);
    for (TopExp_Explorer ex(box, TopAbs_EDGE); ex.More(); ex.Next()) mk.Add(1.0, TopoDS::Edge(ex.Current()));
    const TopoDS_Shape f = mk.Shape();
    auto run = [&](const char* name, auto&& fn) {
      double v = 0, err = 0;
      const auto t0 = Clock::now();
      for (int i = 0; i < 200; ++i) { GProp_GProps p; err = fn(p); v = p.Mass(); }
      std::printf("%-28s %9.6f err=%.2e  %8.1f us\n", name, v, err, std::chrono::duration<double, std::micro>(Clock::now() - t0).count() / 200);
    };
    run("GK 1e-9", [&](GProp_GProps& p) { BRepGProp::VolumePropertiesGK(f, p, 1e-9, true, true); return 0.0; });
    run("GK 1e-6", [&](GProp_GProps& p) { BRepGProp::VolumePropertiesGK(f, p, 1e-6, true, true); return 0.0; });
    run("adaptive 1e-6", [&](GProp_GProps& p) { return BRepGProp::VolumeProperties(f, p, 1e-6, true, true); });
    run("adaptive 1e-4", [&](GProp_GProps& p) { return BRepGProp::VolumeProperties(f, p, 1e-4, true, true); });
    run("fixed order", [&](GProp_GProps& p) { BRepGProp::VolumeProperties(f, p, true, true, false); return 0.0; });
    return 0;
  }
  const std::string first = argc >= 2 ? argv[1] : "";
  std::optional<scad::reactive::Session> session;
  // "<case>_rec": the same operation with a reactive session recording it.
  auto wants_recorder = [&](const std::string& name) { return name.size() > 4 && name.compare(name.size() - 4, 4, "_rec") == 0; };
  const bool wall = argc >= 2 && !std::strcmp(argv[1], "wall");  // wall clock (threads of the kernel's parallel mode do not count twice)
  const bool timing = wall || (argc >= 2 && !std::strcmp(argv[1], "time"));
  const int off = timing ? 2 : 1;
  if (argc < off + 2) return 2;
  const std::string what = argv[off];
  const int n = std::atoi(argv[off + 1]);
  if (wants_recorder(what)) {
    session.emplace();
    session->start();
  }
  if (argc > off + 2 && !std::strcmp(argv[off + 2], "peak")) {
    for (int i = 0; i < 3; ++i) make(what);
    g_keep.clear();
    prof::start();
    const long base = prof::current;  // 0: the logger only sees what is allocated from here on
    make(what);
    prof::stop();
    std::printf("%s peak %.1f KB above the heap before it, %.1f KB kept\n", what.c_str(),
                double(prof::peak - base) / 1024.0, double(prof::current - base) / 1024.0);
    return 0;
  }
  for (int i = 0; i < 5; ++i) make(what);  // warm-up: allocators, static tables
  g_keep.clear();
  if (timing) {
    // CPU time, not wall time: other builds share this machine.
    const std::clock_t c0 = std::clock();
    const auto w0 = Clock::now();
    for (int i = 0; i < n; ++i) { make(what); g_keep.clear(); }
    const double us = wall ? std::chrono::duration<double, std::micro>(Clock::now() - w0).count() / n
                           : 1e6 * double(std::clock() - c0) / CLOCKS_PER_SEC / n;
    std::printf("%s %.1f us/object\n", what.c_str(), us);
    return 0;
  }
  if (argc > off + 2 && !std::strcmp(argv[off + 2], "prof")) {
    prof::start();
    for (int i = 0; i < n; ++i) make(what);
    prof::stop();
    prof::report(argc > off + 3 ? std::atoi(argv[off + 3]) : 25, 9, n);
    return 0;
  }
  const Heap before = heap();
  for (int i = 0; i < n; ++i) make(what);
  const Heap after = heap();
  std::printf("%s n=%d  %.1f KB/object  %.1f blocks/object\n", what.c_str(), n,
              double(after.bytes - before.bytes) / n / 1024.0, double(after.blocks - before.blocks) / n);
  return 0;
}
