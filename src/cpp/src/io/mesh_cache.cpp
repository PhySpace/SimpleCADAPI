// cached_mesh(): derived data kept per shape identity in a bounded LRU.
//
// The Python SDK keeps the mesh in the solid's runtime dictionary, so it dies
// with the solid.  A Shape here is a handle over shared state we do not own, so
// the cache is process-wide and bounded instead; an entry holds the TopoDS_Shape
// it was built from, which keeps the identity (TShape pointer) from being
// recycled for a different shape while the entry lives.
#include <list>
#include <mutex>

#include "scad/core/error.hpp"
#include "scad/io/mesh.hpp"

namespace scad::io {

namespace {

constexpr std::size_t kMaxEntries = 32;
constexpr std::size_t kMaxBytes = std::size_t{256} << 20;

constexpr const char* kErrorKey = "mesh.error";

struct Entry {
  TopoDS_Shape shape;
  double linear = 0.0;
  double angular = 0.0;
  std::shared_ptr<const TriMesh> mesh;
  std::size_t bytes = 0;
};

class Cache {
 public:
  std::shared_ptr<const TriMesh> find(const TopoDS_Shape& shape, double linear, double angular) {
    const std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = entries_.begin(); it != entries_.end(); ++it) {
      if (it->linear == linear && it->angular == angular && it->shape.IsEqual(shape)) {
        entries_.splice(entries_.begin(), entries_, it);  // most recently used first
        return it->mesh;
      }
    }
    return nullptr;
  }

  void insert(const TopoDS_Shape& shape, double linear, double angular, std::shared_ptr<const TriMesh> mesh) {
    Entry entry;
    entry.shape = shape;
    entry.linear = linear;
    entry.angular = angular;
    entry.bytes = mesh->vertices.size() * sizeof(double) + mesh->triangles.size() * sizeof(std::int64_t) +
                  mesh->corner_normals.size() * sizeof(double);
    entry.mesh = std::move(mesh);
    const std::lock_guard<std::mutex> lock(mutex_);
    bytes_ += entry.bytes;
    entries_.push_front(std::move(entry));
    while (entries_.size() > kMaxEntries || (bytes_ > kMaxBytes && entries_.size() > 1)) {
      bytes_ -= entries_.back().bytes;
      entries_.pop_back();
    }
  }

  void clear() {
    const std::lock_guard<std::mutex> lock(mutex_);
    entries_.clear();
    bytes_ = 0;
  }

 private:
  std::mutex mutex_;
  std::list<Entry> entries_;
  std::size_t bytes_ = 0;
};

Cache& cache() {
  static Cache instance;
  return instance;
}

}  // namespace

std::shared_ptr<const TriMesh> cached_mesh_detached(const Shape& solid, double linear_tolerance,
                                                    double angular_tolerance, std::string* error) {
  if (auto hit = cache().find(solid.wrapped(), linear_tolerance, angular_tolerance))
    return hit;
  try {
    auto built = std::make_shared<const TriMesh>(build_solid_trimesh(solid, linear_tolerance, angular_tolerance));
    cache().insert(solid.wrapped(), linear_tolerance, angular_tolerance, built);
    return built;
  } catch (const std::exception& failure) {
    if (error != nullptr)
      *error = failure.what();
    return nullptr;
  }
}

std::shared_ptr<const TriMesh> cached_mesh(const Shape& solid, double linear_tolerance, double angular_tolerance) {
  std::string error;
  auto mesh = cached_mesh_detached(solid, linear_tolerance, angular_tolerance, &error);
  if (!mesh && !error.empty()) {
    Shape handle = solid;  // handles share their entity: this records on the caller's shape
    handle.set_runtime(kErrorKey, error);
  }
  return mesh;
}

std::string mesh_error(const Shape& solid) {
  const Value value = solid.get_runtime(kErrorKey);
  return value.is_string() ? value.as_string() : std::string();
}

void clear_mesh_cache() {
  cache().clear();
}

}  // namespace scad::io
