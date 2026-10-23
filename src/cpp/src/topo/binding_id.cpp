#include "scad/topo/binding_id.hpp"

#include "scad/core/symbol.hpp"

namespace scad {

namespace {

constexpr std::uint64_t kInterned = ~std::uint64_t{0};
constexpr std::string_view kPrefix = "tag_binding_";
constexpr char kHex[] = "0123456789abcdef";

int hex_value(char c) noexcept {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

}  // namespace

BindingId::BindingId() : hi_(kInterned), lo_(0) {}  // symbol 0 is the empty string

BindingId BindingId::from_words(std::uint64_t hi, std::uint64_t lo) noexcept {
  BindingId id;
  id.hi_ = hi == kInterned ? hi ^ 1u : hi;
  id.lo_ = lo;
  return id;
}

BindingId::BindingId(std::string_view text) {
  if (text.size() == kPrefix.size() + 32 && text.substr(0, kPrefix.size()) == kPrefix) {
    std::uint64_t words[2] = {0, 0};
    bool ok = true;
    for (std::size_t i = 0; i < 32 && ok; ++i) {
      const int v = hex_value(text[kPrefix.size() + i]);
      if (v < 0) ok = false;
      else words[i / 16] = (words[i / 16] << 4) | static_cast<std::uint64_t>(v);
    }
    if (ok && words[0] != kInterned) {
      hi_ = words[0];
      lo_ = words[1];
      return;
    }
  }
  hi_ = kInterned;
  lo_ = Symbol(text).index();
}

bool BindingId::empty() const noexcept {
  return hi_ == kInterned && lo_ == 0;
}

std::string BindingId::str() const {
  if (hi_ == kInterned) return Symbol::from_index(static_cast<std::uint32_t>(lo_)).str();
  std::string out(kPrefix);
  out.reserve(kPrefix.size() + 32);
  for (const std::uint64_t word : {hi_, lo_})
    for (int shift = 60; shift >= 0; shift -= 4) out += kHex[(word >> shift) & 0xFu];
  return out;
}

}  // namespace scad
