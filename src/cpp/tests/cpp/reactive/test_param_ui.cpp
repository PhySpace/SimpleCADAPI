// The `# ui:` grammar and ParamSpec (runtime/params.py).
#include "doctest.h"

#include "scad/reactive/expr.hpp"
#include "scad/reactive/param_ui.hpp"

using namespace scad;
using namespace scad::reactive;

TEST_CASE("a full slider description") {
  const ParamUi ui = parse_ui_comment("slider(10, 40, step=2, unit=\"mm\", label='Width')");
  CHECK(ui.issues.empty());
  CHECK(ui.control == "slider");
  CHECK(*ui.min == UiNumber{10, true});
  CHECK(*ui.max == UiNumber{40, true});
  CHECK(*ui.step == UiNumber{2, true});
  CHECK(*ui.unit == "mm");
  CHECK(*ui.label == "Width");
  CHECK(parse_ui_comment("number(min=0.5, max=-1e1)").min->text() == "0.5");
  CHECK(parse_ui_comment("toggle()").control == "toggle");
}

TEST_CASE("bad descriptions say why and leave nothing behind") {
  const std::pair<const char*, const char*> cases[] = {
      {"dial(1, 2)", "ui comment must be one of ['number', 'slider', 'toggle']: 'dial(1, 2)'"},
      {"slider", "ui comment must be one of ['number', 'slider', 'toggle']: 'slider'"},
      {"slider(1", "cannot parse ui comment 'slider(1'"},
      {"slider(1,2,3)", "too many positional arguments for slider"},
      {"toggle(1)", "too many positional arguments for toggle"},
      {"number(speed=1)", "unknown ui option 'speed'"},
      {"number(min=x)", "ui option min must be a literal"},
      {"number(min='a')", "ui option min must be a number"},
      {"number(min=True)", "ui option min must be a number"},
      {"number(unit=3)", "ui option unit must be a string"},
      {"number(step=0)", "step must be positive"},
  };
  for (const auto& [text, issue] : cases) {
    CAPTURE(text);
    const ParamUi ui = parse_ui_comment(text);
    REQUIRE(ui.issues.size() == 1);
    CHECK(ui.issues[0] == issue);
    CHECK(ui.control.empty());
  }
}

TEST_CASE("the control follows the value unless the description fits it") {
  const auto spec = [](ParamKind kind, Value value, std::string_view text) {
    return make_param_spec("A", kind, std::move(value), parse_ui_comment(text));
  };
  CHECK(spec(ParamKind::Float, 1.5, "").control == "number");
  CHECK(spec(ParamKind::Bool, true, "").control == "toggle");
  CHECK(spec(ParamKind::Float, 1.5, "slider(1, 5)").control == "slider");
  CHECK(spec(ParamKind::Bool, true, "slider(1, 5)").issues == std::vector<std::string>{"slider needs a number; A is a bool"});
  CHECK(spec(ParamKind::Float, 1.5, "toggle()").issues == std::vector<std::string>{"toggle needs a bool; A is a number"});
  CHECK(spec(ParamKind::Float, 1.5, "slider(1)").issues == std::vector<std::string>{"slider needs min and max"});

  const ParamSpec reversed = spec(ParamKind::Float, 1.5, "slider(5, 1)");
  CHECK(reversed.control == "number");
  CHECK_FALSE(reversed.min.has_value());
  CHECK(reversed.issues == std::vector<std::string>{"min 5 is above max 1"});

  const ParamSpec dotted = make_param_spec("Dims.L", ParamKind::Float, 80.0, {});
  CHECK(dotted.to_value().find("label")->as_string() == "L");
}

TEST_CASE("a Var describes itself to an editor") {
  ParamUi ui = parse_ui_comment("slider(50, 200, step=5)");
  const auto var = make_var("od", 100.0, "outer", std::nullopt, units::mm(), std::nullopt, ui);
  const ParamSpec spec = var->param_spec();
  CHECK(spec.declared == "var");
  CHECK(spec.unit == std::optional<std::string>("mm"));
  CHECK(spec.comment == std::optional<std::string>("outer"));
  CHECK(spec.control == "slider");
  CHECK(spec.default_value.as_double() == 100.0);
  // The description is not part of what makes two variables the same.
  CHECK(var->expr_id() == make_var("od", 100.0, "outer", std::nullopt, units::mm())->expr_id());
  CHECK(var->with_default(150.0)->param_spec().control == "slider");
}
