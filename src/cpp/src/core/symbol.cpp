#include "scad/core/symbol.hpp"

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace scad {

class SymbolTable {
 public:
  struct TextHash {
    using is_transparent = void;
    std::size_t operator()(std::string_view s) const noexcept { return std::hash<std::string_view>{}(s); }
  };

  static SymbolTable& instance() {
    static SymbolTable table;
    return table;
  }

  const Symbol::Entry* empty() const noexcept { return by_index_.front(); }

  const Symbol::Entry* intern(std::string_view text) {
    const std::lock_guard<std::mutex> lock(mutex_);
    auto it = items_.find(text);
    if (it == items_.end()) {
      auto entry = std::make_unique<Symbol::Entry>();
      entry->text = std::string(text);
      entry->index = static_cast<std::uint32_t>(by_index_.size());
      by_index_.push_back(entry.get());
      it = items_.emplace(entry->text, std::move(entry)).first;
    }
    return it->second.get();
  }

  const Symbol::Entry* find(std::string_view text) {
    const std::lock_guard<std::mutex> lock(mutex_);
    const auto it = items_.find(text);
    return it == items_.end() ? nullptr : it->second.get();
  }

  const Symbol::Entry* at(std::uint32_t index) {
    const std::lock_guard<std::mutex> lock(mutex_);
    return by_index_.at(index);
  }

  std::size_t count() {
    const std::lock_guard<std::mutex> lock(mutex_);
    return by_index_.size();
  }

 private:
  SymbolTable() {
    auto entry = std::make_unique<Symbol::Entry>();
    by_index_.push_back(entry.get());
    items_.emplace(std::string(), std::move(entry));
  }

  std::mutex mutex_;
  // Entries are heap nodes, so their addresses are stable while the table grows.
  std::unordered_map<std::string, std::unique_ptr<Symbol::Entry>, TextHash, std::equal_to<>> items_;
  std::vector<const Symbol::Entry*> by_index_;
};

Symbol::Symbol() noexcept : entry_(SymbolTable::instance().empty()) {}

namespace {

// Entries are immortal, so a per-thread cache of pointers to them never goes stale and lets the
// common lookup skip the table's lock.
struct ThreadCache {
  struct Slot {
    std::size_t hash = 0;
    const Symbol::Entry* entry = nullptr;
  };
  Slot slots[256];
};

}  // namespace

Symbol::Symbol(std::string_view text) {
  if (text.empty()) {
    entry_ = SymbolTable::instance().empty();
    return;
  }
  thread_local ThreadCache cache;
  const std::size_t hash = std::hash<std::string_view>{}(text);
  ThreadCache::Slot& slot = cache.slots[hash & 255];
  if (slot.entry != nullptr && slot.hash == hash && slot.entry->text == text) {
    entry_ = slot.entry;
    return;
  }
  entry_ = SymbolTable::instance().intern(text);
  slot.hash = hash;
  slot.entry = entry_;
}

std::optional<Symbol> Symbol::find(std::string_view text) {
  if (text.empty()) return Symbol();
  const Entry* entry = SymbolTable::instance().find(text);
  if (entry == nullptr) return std::nullopt;
  Symbol s;
  s.entry_ = entry;
  return s;
}

Symbol Symbol::from_index(std::uint32_t index) {
  Symbol s;
  s.entry_ = SymbolTable::instance().at(index);
  return s;
}

std::size_t Symbol::count() { return SymbolTable::instance().count(); }

}  // namespace scad
