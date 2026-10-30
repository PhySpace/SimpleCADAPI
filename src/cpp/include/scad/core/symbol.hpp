// Symbol: an interned immutable string, one pointer wide.
//
// For vocabularies that repeat across many records (tag names, rule ids, schema
// versions): the text is stored once per process, equality is a pointer compare, and
// the canonical text is always available as a std::string (`str()`), so a value that
// leaves the process or is compared across a boundary is unchanged.
//
// Not for unbounded vocabularies (random node ids, topo ids of every shape): the table
// never shrinks.
#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <string_view>

namespace scad {

class Symbol {
 public:
  Symbol() noexcept;                                                   // the empty string
  Symbol(std::string_view text);                                       // NOLINT(google-explicit-constructor)
  Symbol(const std::string& text) : Symbol(std::string_view(text)) {}  // NOLINT
  Symbol(const char* text) : Symbol(std::string_view(text)) {}         // NOLINT

  // The symbol for `text` if it was ever interned, without interning it: a name nobody
  // interned cannot be held by anything.
  static std::optional<Symbol> find(std::string_view text);

  const std::string& str() const noexcept { return entry_->text; }
  std::string_view view() const noexcept { return entry_->text; }
  bool empty() const noexcept { return entry_->text.empty(); }
  std::size_t size() const noexcept { return entry_->text.size(); }

  operator const std::string&() const noexcept { return entry_->text; }  // NOLINT
  operator std::string_view() const noexcept { return entry_->text; }    // NOLINT

  const void* id() const noexcept { return entry_; }

  // A dense number, stable for the process: how packed records refer to a symbol.
  std::uint32_t index() const noexcept { return entry_->index; }
  static Symbol from_index(std::uint32_t index);
  static std::size_t count();

  friend bool operator==(Symbol a, Symbol b) noexcept { return a.entry_ == b.entry_; }
  friend bool operator!=(Symbol a, Symbol b) noexcept { return a.entry_ != b.entry_; }
  friend bool operator==(Symbol a, std::string_view b) noexcept { return a.view() == b; }
  friend bool operator!=(Symbol a, std::string_view b) noexcept { return a.view() != b; }
  friend bool operator==(Symbol a, const std::string& b) noexcept { return a.view() == b; }
  friend bool operator!=(Symbol a, const std::string& b) noexcept { return a.view() != b; }
  friend bool operator==(Symbol a, const char* b) noexcept { return a.view() == b; }
  friend bool operator!=(Symbol a, const char* b) noexcept { return a.view() != b; }
  friend bool operator<(Symbol a, Symbol b) noexcept { return a.view() < b.view(); }

  // Implementation detail: one per distinct text, immortal.
  struct Entry {
    std::string text;
    std::uint32_t index = 0;
  };

 private:
  friend class SymbolTable;
  const Entry* entry_;
};

}  // namespace scad

template <>
struct std::hash<scad::Symbol> {
  std::size_t operator()(scad::Symbol s) const noexcept { return std::hash<const void*>{}(s.id()); }
};
