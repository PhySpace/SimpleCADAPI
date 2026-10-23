// Cow<T>: a shared, copy-on-write value.
//
// Records that are the same for most of their instances (a producer, a propagation
// policy) are held once and shared by pointer.  Reading goes through operator-> and
// never copies; `mut()` gives a private instance, copying only when the node is shared.
// A default-constructed Cow shares one immortal default node per T, so it costs no
// allocation.
#pragma once

#include <memory>
#include <utility>

namespace scad {

template <class T>
class Cow {
 public:
  Cow() : node_(default_node()) {}
  Cow(T value) : node_(std::make_shared<T>(std::move(value))) {}  // NOLINT(google-explicit-constructor)

  const T& operator*() const noexcept { return *node_; }
  const T* operator->() const noexcept { return node_.get(); }
  const T& get() const noexcept { return *node_; }

  // A mutable instance private to this handle.
  T& mut() {
    if (node_.use_count() != 1) node_ = std::make_shared<T>(*node_);
    return const_cast<T&>(*node_);  // sole owner of a node we created: writing is safe
  }

  bool shares_node_with(const Cow& other) const noexcept { return node_ == other.node_; }

 private:
  static const std::shared_ptr<const T>& default_node() {
    static const std::shared_ptr<const T> node = std::make_shared<T>();
    return node;
  }
  std::shared_ptr<const T> node_;
};

}  // namespace scad
