// BindingId: the identity of a tag binding, 16 bytes.
//
// The canonical text is "tag_binding_<32 hex>" (uuid4 or uuid5 digits); that form is
// stored as the 128 bits.  Any other text (an id imported from elsewhere) is interned
// and kept by pointer, so every id round-trips through `str()` exactly.
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <string_view>

namespace scad {

class BindingId {
 public:
  BindingId();                                                               // the empty id (invalid as a binding id)
  BindingId(std::string_view text);                                          // NOLINT(google-explicit-constructor)
  BindingId(const std::string& text) : BindingId(std::string_view(text)) {}  // NOLINT
  BindingId(const char* text) : BindingId(std::string_view(text)) {}         // NOLINT

  // 128 bits as two words (uuid digits); the one word pattern reserved for interned ids is nudged.
  static BindingId from_words(std::uint64_t hi, std::uint64_t lo) noexcept;

  std::string str() const;
  operator std::string() const { return str(); }  // NOLINT(google-explicit-constructor)
  bool empty() const noexcept;

  std::uint64_t hi() const noexcept { return hi_; }
  std::uint64_t lo() const noexcept { return lo_; }

  friend bool operator==(const BindingId& a, const BindingId& b) noexcept { return a.hi_ == b.hi_ && a.lo_ == b.lo_; }
  friend bool operator!=(const BindingId& a, const BindingId& b) noexcept { return !(a == b); }
  friend bool operator==(const BindingId& a, std::string_view b) { return a == BindingId(b); }
  friend bool operator==(const BindingId& a, const std::string& b) { return a == BindingId(std::string_view(b)); }
  friend bool operator==(const BindingId& a, const char* b) { return a == BindingId(std::string_view(b)); }
  friend bool operator<(const BindingId& a, const BindingId& b) noexcept {
    return a.hi_ != b.hi_ ? a.hi_ < b.hi_ : a.lo_ < b.lo_;
  }

 private:
  std::uint64_t hi_;  // kInterned: `lo_` is the index of an interned Symbol
  std::uint64_t lo_;
};

}  // namespace scad

template <>
struct std::hash<scad::BindingId> {
  std::size_t operator()(const scad::BindingId& id) const noexcept {
    return static_cast<std::size_t>(id.hi() * 0x9E3779B97F4A7C15ull ^ id.lo());
  }
};
