#include "scad/reactive/param_ui.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <utility>

#include "scad/reactive/digest.hpp"

namespace scad::reactive {

std::string UiNumber::text() const {
  if (integral) return std::to_string(static_cast<long long>(value));
  return py_float_repr(value);
}

Value UiNumber::to_value() const {
  return integral ? Value(static_cast<std::int64_t>(value)) : Value(value);
}

std::string_view to_string(ParamKind kind) noexcept {
  switch (kind) {
    case ParamKind::Float: return "float";
    case ParamKind::Int: return "int";
    case ParamKind::Bool: return "bool";
  }
  return "float";
}

namespace {

// A literal of the ui grammar: number, string, True/False/None.
struct Literal {
  enum class Type { Number, String, Bool, None, NonLiteral } type = Type::None;
  UiNumber number;
  std::string text;
};

struct Argument {
  std::string key;  // empty: positional
  Literal value;
};

struct Call {
  std::string callee;
  std::vector<Argument> args;
};

// A small recursive-descent reader for `name(literal, key=literal, ...)`.
// Anything that is not that shape is reported through the Outcome.
class Reader {
 public:
  explicit Reader(std::string_view text) : text_(text) {}

  enum class Outcome { Call, NotACall, SyntaxError };

  Outcome read(Call& out) {
    skip_blanks();
    std::string name;
    if (!identifier(name)) return fail_kind();
    skip_blanks();
    if (!consume('(')) return at_end() ? Outcome::NotACall : Outcome::SyntaxError;
    out.callee = name;
    skip_blanks();
    if (consume(')')) return finish();
    while (true) {
      Argument arg;
      skip_blanks();
      const std::size_t mark = pos_;
      std::string key;
      if (identifier(key)) {
        skip_blanks();
        if (consume('=') && !peek_is('=')) {
          arg.key = key;
        } else {
          pos_ = mark;
        }
      }
      if (!argument_value(arg)) return Outcome::SyntaxError;
      out.args.push_back(std::move(arg));
      skip_blanks();
      if (consume(',')) {
        skip_blanks();
        if (consume(')')) return finish();
        continue;
      }
      if (consume(')')) return finish();
      return Outcome::SyntaxError;
    }
  }

 private:
  Outcome finish() {
    skip_blanks();
    return at_end() ? Outcome::Call : Outcome::SyntaxError;
  }
  Outcome fail_kind() {
    // Not an identifier: a bare number or string is a valid expression but not a call.
    Argument probe;
    pos_ = 0;
    skip_blanks();
    if (argument_value(probe)) {
      skip_blanks();
      if (at_end()) return Outcome::NotACall;
    }
    return Outcome::SyntaxError;
  }

  bool at_end() const { return pos_ >= text_.size(); }
  bool peek_is(char c) const { return pos_ < text_.size() && text_[pos_] == c; }
  bool consume(char c) {
    if (!peek_is(c)) return false;
    ++pos_;
    return true;
  }
  void skip_blanks() {
    while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_]))) ++pos_;
  }
  bool identifier(std::string& out) {
    const std::size_t start = pos_;
    if (pos_ < text_.size() && (std::isalpha(static_cast<unsigned char>(text_[pos_])) || text_[pos_] == '_')) {
      ++pos_;
      while (pos_ < text_.size() && (std::isalnum(static_cast<unsigned char>(text_[pos_])) || text_[pos_] == '_')) ++pos_;
      out.assign(text_.substr(start, pos_ - start));
      return true;
    }
    return false;
  }

  bool argument_value(Argument& arg) {
    skip_blanks();
    if (pos_ >= text_.size()) return false;
    const char c = text_[pos_];
    if (c == '"' || c == '\'') return string_literal(arg.value);
    if (c == '-' || c == '+' || c == '.' || std::isdigit(static_cast<unsigned char>(c))) return number_literal(arg.value);
    std::string word;
    const std::size_t mark = pos_;
    if (identifier(word)) {
      if (word == "True" || word == "False") {
        arg.value.type = Literal::Type::Bool;
        return true;
      }
      if (word == "None") {
        arg.value.type = Literal::Type::None;
        return true;
      }
      // A name (or dotted name): a valid expression, just not a literal.
      while (peek_is('.')) {
        ++pos_;
        if (!identifier(word)) {
          pos_ = mark;
          return false;
        }
      }
      arg.value.type = Literal::Type::NonLiteral;
      return true;
    }
    return false;
  }

  bool number_literal(Literal& out) {
    const std::size_t start = pos_;
    if (text_[pos_] == '-' || text_[pos_] == '+') ++pos_;
    bool integral = true;
    const std::size_t digits_from = pos_;
    while (pos_ < text_.size() && (std::isdigit(static_cast<unsigned char>(text_[pos_])) || text_[pos_] == '_')) ++pos_;
    if (peek_is('.')) {
      integral = false;
      ++pos_;
      while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) ++pos_;
    }
    if (pos_ < text_.size() && (text_[pos_] == 'e' || text_[pos_] == 'E')) {
      std::size_t probe = pos_ + 1;
      if (probe < text_.size() && (text_[probe] == '+' || text_[probe] == '-')) ++probe;
      if (probe < text_.size() && std::isdigit(static_cast<unsigned char>(text_[probe]))) {
        integral = false;
        pos_ = probe;
        while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_]))) ++pos_;
      }
    }
    if (pos_ == digits_from || (pos_ == digits_from + 1 && text_[digits_from] == '.')) return false;
    std::string number(text_.substr(start, pos_ - start));
    number.erase(std::remove(number.begin(), number.end(), '_'), number.end());
    out.type = Literal::Type::Number;
    out.number = UiNumber{std::strtod(number.c_str(), nullptr), integral};
    return true;
  }

  bool string_literal(Literal& out) {
    const char quote = text_[pos_++];
    std::string value;
    while (pos_ < text_.size() && text_[pos_] != quote) {
      char c = text_[pos_++];
      if (c == '\\' && pos_ < text_.size()) {
        const char escaped = text_[pos_++];
        switch (escaped) {
          case 'n': c = '\n'; break;
          case 't': c = '\t'; break;
          default: c = escaped; break;
        }
      }
      value += c;
    }
    if (!consume(quote)) return false;
    out.type = Literal::Type::String;
    out.text = std::move(value);
    return true;
  }

  std::string_view text_;
  std::size_t pos_ = 0;
};

constexpr std::string_view kControlList = "['number', 'slider', 'toggle']";

bool is_control(std::string_view name) { return name == "slider" || name == "number" || name == "toggle"; }

}  // namespace

ParamUi parse_ui_comment(std::string_view text) {
  ParamUi ui;
  Call call;
  switch (Reader(text).read(call)) {
    case Reader::Outcome::SyntaxError:
      ui.issues.push_back("cannot parse ui comment " + py_str_repr(text));
      return ui;
    case Reader::Outcome::NotACall:
      ui.issues.push_back("ui comment must be one of " + std::string(kControlList) + ": " + py_str_repr(text));
      return ui;
    case Reader::Outcome::Call: break;
  }
  if (!is_control(call.callee)) {
    ui.issues.push_back("ui comment must be one of " + std::string(kControlList) + ": " + py_str_repr(text));
    return ui;
  }
  const bool toggle = call.callee == "toggle";
  const std::size_t positional_limit = toggle ? 0 : 2;
  std::size_t positional = 0;
  for (const Argument& arg : call.args) positional += arg.key.empty() ? 1 : 0;
  if (positional > positional_limit) {
    ui.issues.push_back("too many positional arguments for " + call.callee);
    return ui;
  }

  ParamUi parsed;
  parsed.control = call.callee;
  std::size_t next_positional = 0;
  for (const Argument& arg : call.args) {
    std::string key = arg.key;
    if (key.empty()) key = next_positional++ == 0 ? "min" : "max";
    if (key != "min" && key != "max" && key != "step" && key != "unit" && key != "label") {
      ui.issues.push_back("unknown ui option " + py_str_repr(key));
      return ui;
    }
    if (arg.value.type == Literal::Type::NonLiteral) {
      ui.issues.push_back("ui option " + key + " must be a literal");
      return ui;
    }
    if (key == "min" || key == "max" || key == "step") {
      if (arg.value.type != Literal::Type::Number) {
        ui.issues.push_back("ui option " + key + " must be a number");
        return ui;
      }
      (key == "min" ? parsed.min : key == "max" ? parsed.max : parsed.step) = arg.value.number;
    } else {
      if (arg.value.type != Literal::Type::String) {
        ui.issues.push_back("ui option " + key + " must be a string");
        return ui;
      }
      (key == "unit" ? parsed.unit : parsed.label) = arg.value.text;
    }
  }
  if (parsed.step && parsed.step->value <= 0) {
    ui.issues.push_back("step must be positive");
    return ui;
  }
  return parsed;
}

Value ParamSpec::to_value() const {
  Value out = Value::object();
  out.set("name", name);
  out.set("group", group);
  out.set("cell", cell);
  out.set("line", line);
  out.set("kind", std::string(to_string(kind)));
  out.set("declared", declared);
  out.set("default", default_value);
  out.set("control", control);
  out.set("min", min ? min->to_value() : Value());
  out.set("max", max ? max->to_value() : Value());
  out.set("step", step ? step->to_value() : Value());
  out.set("unit", unit ? Value(*unit) : Value());
  const std::size_t dot = name.rfind('.');
  out.set("label", label && !label->empty() ? *label : (dot == std::string::npos ? name : name.substr(dot + 1)));
  out.set("comment", comment ? Value(*comment) : Value());
  Value list = Value::array();
  for (const std::string& issue : issues) list.push_back(issue);
  out.set("issues", list);
  return out;
}

ParamSpec make_param_spec(std::string name, ParamKind kind, Value default_value, const ParamUi& ui,
                          std::string declared, std::optional<std::string> unit, std::optional<std::string> comment) {
  ParamSpec spec;
  spec.name = std::move(name);
  spec.kind = kind;
  spec.declared = std::move(declared);
  spec.default_value = std::move(default_value);
  spec.group = ui.group;
  spec.issues = ui.issues;
  spec.control = kind == ParamKind::Bool ? "toggle" : "number";
  spec.comment = std::move(comment);

  std::optional<UiNumber> lower, upper;
  if (!ui.control.empty()) {
    const std::string& requested = ui.control;
    if (kind == ParamKind::Bool && requested != "toggle") {
      spec.issues.push_back(requested + " needs a number; " + spec.name + " is a bool");
    } else if (kind != ParamKind::Bool && requested == "toggle") {
      spec.issues.push_back("toggle needs a bool; " + spec.name + " is a number");
    } else if (requested == "slider" && (!ui.min || !ui.max)) {
      spec.issues.push_back("slider needs min and max");
    } else {
      spec.control = requested;
    }
    lower = ui.min;
    upper = ui.max;
  }
  if (lower && upper && lower->value > upper->value) {
    spec.issues.push_back("min " + lower->text() + " is above max " + upper->text());
    lower.reset();
    upper.reset();
    if (kind != ParamKind::Bool) spec.control = "number";
  }
  spec.min = lower;
  spec.max = upper;
  spec.step = ui.step;
  spec.unit = ui.unit ? ui.unit : std::move(unit);
  spec.label = ui.label;
  return spec;
}

}  // namespace scad::reactive
