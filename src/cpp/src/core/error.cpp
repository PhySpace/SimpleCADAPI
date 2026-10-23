#include "scad/core/error.hpp"

#include <cstdio>
#include <new>
#include <utility>

namespace scad {

namespace {

std::string& module_name_storage() {
  static std::string name = "simplecadapi";
  return name;
}

std::string trimmed(std::string_view text) {
  const auto first = text.find_first_not_of(" \t\r\n");
  if (first == std::string_view::npos) return {};
  const auto last = text.find_last_not_of(" \t\r\n");
  return std::string(text.substr(first, last - first + 1));
}

std::vector<std::string> normalized_lines(const std::vector<std::string>& lines) {
  std::vector<std::string> out;
  out.reserve(lines.size());
  for (const auto& line : lines) {
    std::string t = trimmed(line);
    if (!t.empty()) out.push_back(std::move(t));
  }
  return out;
}

std::string general(double v) {
  char buf[64];
  std::snprintf(buf, sizeof buf, "%.4g", v);
  return buf;
}

std::string documentation_hint(std::string_view operation) {
  const std::string op = trimmed(operation);
  if (op.empty()) return "For full usage details, run help(...) on the failing operation.";
  if (op.find('.') != std::string::npos) return "For full usage details, run help(" + op + ").";
  return "For full usage details, run help(" + module_name_storage() + "." + op + ").";
}

}  // namespace

std::string_view py_kind_name(PyKind kind) noexcept {
  switch (kind) {
    case PyKind::ValueError: return "ValueError";
    case PyKind::TypeError: return "TypeError";
    case PyKind::IndexError: return "IndexError";
    case PyKind::KeyError: return "KeyError";
    case PyKind::RuntimeError: return "RuntimeError";
    case PyKind::NotImplementedError: return "NotImplementedError";
  }
  return "RuntimeError";
}

void set_error_module_name(std::string name) { module_name_storage() = std::move(name); }
const std::string& error_module_name() { return module_name_storage(); }

std::string ErrorMeasurement::display() const {
  std::string rendered;
  if (const auto* scalar = std::get_if<double>(&value)) {
    rendered = general(*scalar);
  } else {
    const auto& v = std::get<std::array<double, 3>>(value);
    rendered = "(" + general(v[0]) + ", " + general(v[1]) + ", " + general(v[2]) + ")";
  }
  std::string out = name + ": " + rendered;
  if (!unit.empty()) out += " " + unit;
  return out;
}

std::string format_llm_error(std::string_view operation, const ErrorGuidance& g) {
  std::string out;
  const auto line = [&out](const std::string& text) {
    if (!out.empty()) out += '\n';
    out += text;
  };
  line("Operation: " + std::string(operation));
  if (!g.signature.empty()) line("Signature: " + g.signature);
  if (!g.documentation_hint.empty()) line("Documentation: " + g.documentation_hint);
  line("What happened: " + g.what_happened);
  if (!g.measurements.empty()) {
    line("Measurements:");
    for (const auto& m : g.measurements) line("- " + m.display());
  }
  if (!g.evidence.empty()) {
    line("Evidence:");
    for (const auto& e : g.evidence) {
      std::string rendered = "- " + e.kind + " view '" + (e.view.empty() ? "default" : e.view) + "'";
      if (!e.path.empty()) rendered += ": " + e.path;
      if (!e.caption.empty()) rendered += " (" + e.caption + ")";
      line(rendered);
      if (!e.symbols.empty()) {
        std::string table;
        for (const auto& [symbol, description] : e.symbols) {
          if (!table.empty()) table += ", ";
          table += symbol + "=" + description;
        }
        line("  symbols: " + table);
      }
    }
  }
  line("Possible causes:");
  for (const auto& cause : g.possible_causes) line("- " + cause);
  line("How to fix:");
  for (const auto& fix : g.repair) line("- " + fix);
  for (const auto& fix : g.how_to_fix) line("- " + fix);
  if (!g.inventory.empty()) {
    line("Inventory:");
    for (const auto& entry : g.inventory)
      line("- " + entry.symbol + " [" + entry.status + "] " + entry.description);
  }
  if (!g.technical_details.empty()) line("Technical details: " + g.technical_details);
  return out;
}

Error::Error(std::string operation, ErrorGuidance guidance)
    : ValueError(format_llm_error(operation, guidance)),
      operation_(std::move(operation)),
      guidance_(std::move(guidance)) {}

namespace {

// _contains_cjk: a code point in U+3400..U+9FFF or U+F900..U+FAFF, read off the UTF-8 lead bytes.
bool contains_cjk(std::string_view text) {
  for (std::size_t i = 0; i + 2 < text.size(); ++i) {
    const auto lead = static_cast<unsigned char>(text[i]);
    const auto second = static_cast<unsigned char>(text[i + 1]);
    if ((lead == 0xE3 && second >= 0x90) || (lead >= 0xE4 && lead <= 0xE9)) return true;
    if (lead == 0xEF && second >= 0xA4 && second <= 0xAB) return true;
  }
  return false;
}

// _technical_details_from_error: every message the SDK writes is English; text of another origin that is not
// (a kernel or a user callback) is replaced by a generic sentence.
std::string readable_message(std::string message) {
  if (contains_cjk(message)) {
    return "The underlying validation failed; use the structured guidance above to repair the operation.";
  }
  return message;
}

}  // namespace

std::string technical_details_of(const std::exception& error) {
  std::string_view type = "RuntimeError";
  if (const auto* e = dynamic_cast<const KernelError*>(&error)) {
    const std::string msg = readable_message(trimmed(e->what()));
    return e->occt_class() + (msg.empty() ? "" : ": " + msg);
  }
  if (const auto* e = dynamic_cast<const Exception*>(&error)) {
    type = py_kind_name(e->py_kind());
  } else if (dynamic_cast<const std::invalid_argument*>(&error) ||
             dynamic_cast<const std::domain_error*>(&error)) {
    type = "ValueError";
  } else if (dynamic_cast<const std::out_of_range*>(&error)) {
    type = "IndexError";
  } else if (dynamic_cast<const std::bad_alloc*>(&error)) {
    type = "MemoryError";
  }
  const std::string msg = readable_message(trimmed(error.what()));
  return std::string(type) + (msg.empty() ? "" : ": " + msg);
}

namespace {

[[noreturn]] void throw_wrapped(const ErrorSpec& spec, std::string details,
                                std::vector<ErrorMeasurement> measurements,
                                std::vector<std::string> repair,
                                std::vector<InventoryEntry> inventory,
                                std::vector<ErrorEvidence> evidence) {
  ErrorGuidance g;
  g.what_happened = trimmed(spec.what_happened);
  g.possible_causes = normalized_lines(spec.possible_causes);
  g.how_to_fix = normalized_lines(spec.how_to_fix);
  g.technical_details = trimmed(details);
  g.documentation_hint = documentation_hint(spec.operation);
  g.measurements = std::move(measurements);
  g.repair = normalized_lines(repair);
  g.inventory = std::move(inventory);
  g.evidence = std::move(evidence);
  throw Error(spec.operation, std::move(g));
}

}  // namespace

void raise_harness_error(const ErrorSpec& spec, const std::exception& cause,
                         std::vector<ErrorMeasurement> measurements, std::vector<std::string> repair,
                         std::vector<InventoryEntry> inventory, std::vector<ErrorEvidence> evidence) {
  if (const auto* existing = dynamic_cast<const Error*>(&cause)) throw *existing;
  throw_wrapped(spec, technical_details_of(cause), std::move(measurements), std::move(repair),
                std::move(inventory), std::move(evidence));
}

void raise_harness_error(const ErrorSpec& spec, std::string technical_details,
                         std::vector<ErrorMeasurement> measurements, std::vector<std::string> repair,
                         std::vector<InventoryEntry> inventory, std::vector<ErrorEvidence> evidence) {
  throw_wrapped(spec, std::move(technical_details), std::move(measurements), std::move(repair),
                std::move(inventory), std::move(evidence));
}

}  // namespace scad
