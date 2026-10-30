#include "scad/reactive/expr.hpp"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <numbers>
#include <unordered_set>

#include "scad/reactive/digest.hpp"

namespace scad::reactive {

namespace {

double finite_scalar(double value, std::string_view label) {
  if (!std::isfinite(value))
    throw ValueError(std::string(label) + " must be finite");
  return value;
}

std::string tuple_text(const std::vector<std::string>& items) {
  std::string out = "(";
  for (std::size_t i = 0; i < items.size(); ++i)
    out += (i == 0 ? "" : ", ") + items[i];
  if (items.size() == 1)
    out += ",";
  return out + ")";
}

std::string hex_text(double value) {
  return py_str_repr(py_float_hex(value));
}

std::string unit_signature(const Unit& unit) {
  return tuple_text({py_str_repr(unit.symbol()), std::to_string(unit.dimension().length),
                     std::to_string(unit.dimension().angle), hex_text(unit.scale_to_canonical())});
}

std::string optional_unit_signature(const std::optional<Unit>& unit) {
  return unit ? unit_signature(*unit) : "None";
}

std::string var_signature(const VarSpec& spec) {
  std::string tolerance = "None";
  if (spec.tolerance) {
    tolerance = tuple_text({hex_text(spec.tolerance->lower_deviation()), hex_text(spec.tolerance->upper_deviation())});
  }
  return tuple_text({"'var'", py_str_repr(spec.name), hex_text(spec.default_value),
                     spec.comment ? py_str_repr(*spec.comment) : "None", tolerance, optional_unit_signature(spec.unit),
                     optional_unit_signature(spec.tolerance_unit)});
}

std::string structural_id(std::string_view prefix, const std::string& signature) {
  return std::string(prefix) + "_" + sha256_hex(signature).substr(0, 16);
}

// ---------------------------------------------------------------------------
// Inference (units.py: _infer)
// ---------------------------------------------------------------------------

Dimension dimension_of(const Inference& item) {
  if (!item.dimension)
    throw UnitValidationError("Expression operand has no inferable dimension");
  return *item.dimension;
}

[[noreturn]] void mixed_legacy(std::string_view op) {
  throw UnitValidationError("Expression operation '" + std::string(op) +
                            "' mixes unit-declared variables with legacy variables that have no unit");
}

void require_no_mixed_legacy(std::string_view op, const std::vector<Inference>& items) {
  const bool typed = std::any_of(items.begin(), items.end(), [](const Inference& i) { return i.typed; });
  const bool legacy = std::any_of(items.begin(), items.end(), [](const Inference& i) { return i.legacy; });
  if (typed && legacy)
    mixed_legacy(op);
}

std::optional<Dimension> same_dimension(std::string_view op, const Inference& left, const Inference& right) {
  require_no_mixed_legacy(op, {left, right});
  if (left.legacy || right.legacy)
    return std::nullopt;
  if (left.constant && !left.typed)
    return right.dimension;
  if (right.constant && !right.typed)
    return left.dimension;
  if (left.dimension != right.dimension) {
    const auto name = [](const std::optional<Dimension>& d) { return d ? d->name() : std::string("Unknown"); };
    throw UnitValidationError("Expression operation '" + std::string(op) + "' requires matching dimensions; got " +
                              name(left.dimension) + " and " + name(right.dimension));
  }
  return left.dimension;
}

Inference infer_expression(const std::string& op, const std::vector<ScalarPtr>& operands) {
  std::vector<Inference> args;
  args.reserve(operands.size());
  for (const ScalarPtr& operand : operands)
    args.push_back(operand->inference());
  const bool typed = std::any_of(args.begin(), args.end(), [](const Inference& i) { return i.typed; });
  const bool legacy = std::any_of(args.begin(), args.end(), [](const Inference& i) { return i.legacy; });
  const bool constant = std::all_of(args.begin(), args.end(), [](const Inference& i) { return i.constant; });

  std::optional<Dimension> dimension;
  if (op == "add" || op == "sub") {
    dimension = same_dimension(op, args[0], args[1]);
  } else if (op == "mul") {
    require_no_mixed_legacy(op, args);
    if (!legacy)
      dimension = dimension_of(args[0]).multiply(dimension_of(args[1]));
  } else if (op == "div") {
    require_no_mixed_legacy(op, args);
    if (!legacy)
      dimension = dimension_of(args[0]).divide(dimension_of(args[1]));
  } else if (op == "pow") {
    require_no_mixed_legacy(op, args);
    if (!typed) {
      if (!legacy)
        dimension = kDimensionless;
    } else {
      if (args[1].legacy || args[1].dimension != kDimensionless) {
        throw UnitValidationError("A physical quantity exponent must be dimensionless");
      }
      if (args[0].dimension == kDimensionless) {
        dimension = kDimensionless;
      } else {
        if (!args[1].constant) {
          throw UnitValidationError("A dimensioned expression requires a constant numeric exponent");
        }
        const double exponent = operands[1]->eval_unchecked(nullptr);
        if (std::isfinite(exponent) && std::floor(exponent) == exponent && std::fabs(exponent) < 1e6) {
          dimension = dimension_of(args[0]).power(static_cast<int>(exponent));
        } else if (exponent == 0.5) {
          dimension = dimension_of(args[0]).square_root();
        } else {
          throw UnitValidationError("Dimensioned powers currently support integer exponents or 0.5");
        }
      }
    }
  } else if (op == "neg" || op == "abs") {
    dimension = args[0].dimension;
  } else if (op == "sqrt") {
    if (!legacy)
      dimension = dimension_of(args[0]).square_root();
  } else if (op == "sin" || op == "cos" || op == "tan") {
    if (typed && args[0].dimension != kAngle) {
      throw UnitValidationError("Expression operation '" + op + "' requires an Angle input");
    }
    if (!legacy)
      dimension = kDimensionless;
  } else if (op == "asin" || op == "acos" || op == "atan") {
    if (typed && args[0].dimension != kDimensionless) {
      throw UnitValidationError("Expression operation '" + op + "' requires a Dimensionless input");
    }
    if (typed)
      dimension = kAngle;
  } else if (op == "atan2") {
    dimension = same_dimension(op, args[0], args[1]);
    if (dimension && typed) {
      dimension = kAngle;
    } else if (!typed) {
      dimension.reset();
    }
  } else {
    throw UnitValidationError("Unsupported expression operation '" + op + "' for unit inference");
  }
  return Inference{dimension, typed, legacy, constant};
}

// ---------------------------------------------------------------------------
// Evaluation (expr.py: Expr.evaluate)
// ---------------------------------------------------------------------------

constexpr double radians(double degrees) {
  return degrees * (std::numbers::pi / 180.0);
}
constexpr double degrees(double radians_) {
  return radians_ * (180.0 / std::numbers::pi);
}

double checked_pow(double base, double exponent) {
  if (base == 0.0 && exponent < 0.0)
    throw ValueError("0.0 cannot be raised to a negative power");
  if (base < 0.0 && std::floor(exponent) != exponent) {
    throw ValueError("negative number cannot be raised to a fractional power");
  }
  const double result = std::pow(base, exponent);
  if (std::isinf(result) && std::isfinite(base) && std::isfinite(exponent)) {
    throw ValueError("math range error: the result of pow is out of range");
  }
  return result;
}

double unit_domain(double value, std::string_view fn) {
  if (value < -1.0 || value > 1.0)
    throw ValueError("math domain error (" + std::string(fn) + ")");
  return value;
}

}  // namespace

// ---------------------------------------------------------------------------
// DimensionTolerance
// ---------------------------------------------------------------------------

DimensionTolerance::DimensionTolerance(double lower_deviation, double upper_deviation)
    : lower_(finite_scalar(lower_deviation, "lower_deviation")),
      upper_(finite_scalar(upper_deviation, "upper_deviation")) {
  if (lower_ > 0.0)
    throw ValueError("lower_deviation must be less than or equal to zero");
  if (upper_ < 0.0)
    throw ValueError("upper_deviation must be greater than or equal to zero");
}

DimensionTolerance DimensionTolerance::symmetric(double deviation) {
  const double value = finite_scalar(deviation, "deviation");
  if (value < 0.0)
    throw ValueError("deviation must be greater than or equal to zero");
  return DimensionTolerance(-value, value);
}

Value DimensionTolerance::to_value() const {
  Value out = Value::object();
  out.set("lower_deviation", lower_);
  out.set("upper_deviation", upper_);
  return out;
}

DimensionTolerance DimensionTolerance::from_value(const Value& payload) {
  if (!payload.is_object())
    throw TypeError("Dimension tolerance payload must be an object");
  const Value* lower = payload.find("lower_deviation");
  const Value* upper = payload.find("upper_deviation");
  if (lower == nullptr || upper == nullptr) {
    throw ValueError("Dimension tolerance payload requires lower_deviation and upper_deviation");
  }
  if (!lower->is_number())
    throw TypeError("lower_deviation must be a real number");
  if (!upper->is_number())
    throw TypeError("upper_deviation must be a real number");
  return DimensionTolerance(lower->as_double(), upper->as_double());
}

// ---------------------------------------------------------------------------
// Signature, ids, equality
// ---------------------------------------------------------------------------

std::string expr_signature(const ScalarNode& node) {
  switch (node.type()) {
    case NodeType::Const:
      return tuple_text({"'const'", hex_text(static_cast<const Const&>(node).value())});
    case NodeType::Var:
      return var_signature(static_cast<const Var&>(node).spec());
    case NodeType::Expr: {
      const auto& e = static_cast<const Expr&>(node);
      std::vector<std::string> ids;
      ids.reserve(e.args().size());
      for (const ScalarPtr& arg : e.args())
        ids.push_back(py_str_repr(arg->expr_id()));
      return tuple_text({"'expr'", py_str_repr(e.op()), tuple_text(ids)});
    }
  }
  return {};
}

bool same_expression(const ScalarNode& a, const ScalarNode& b) {
  if (&a == &b)
    return true;
  if (a.type() != b.type() || a.expr_id() != b.expr_id())
    return false;
  switch (a.type()) {
    case NodeType::Const:
      return static_cast<const Const&>(a).value() == static_cast<const Const&>(b).value();
    case NodeType::Var: {
      const auto& x = static_cast<const Var&>(a);
      const auto& y = static_cast<const Var&>(b);
      return x.name() == y.name() && x.default_value() == y.default_value() && x.comment() == y.comment() &&
             x.tolerance() == y.tolerance() && x.unit() == y.unit() && x.tolerance_unit() == y.tolerance_unit();
    }
    case NodeType::Expr: {
      const auto& x = static_cast<const Expr&>(a);
      const auto& y = static_cast<const Expr&>(b);
      if (x.op() != y.op() || x.args().size() != y.args().size())
        return false;
      for (std::size_t i = 0; i < x.args().size(); ++i) {
        if (!same_expression(*x.args()[i], *y.args()[i]))
          return false;
      }
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// repr (Python dataclass text)
// ---------------------------------------------------------------------------

namespace {

std::string unit_repr(const Unit& u) {
  return "Unit(symbol=" + py_str_repr(u.symbol()) +
         ", dimension=Dimension(length=" + std::to_string(u.dimension().length) +
         ", angle=" + std::to_string(u.dimension().angle) +
         "), scale_to_canonical=" + py_float_repr(u.scale_to_canonical()) + ")";
}

std::string optional_unit_repr(const std::optional<Unit>& u) {
  return u ? unit_repr(*u) : "None";
}

}  // namespace

std::string ScalarNode::repr() const {
  switch (type()) {
    case NodeType::Const: {
      const auto& c = static_cast<const Const&>(*this);
      return "Const(value=" + py_float_repr(c.value()) + ", expr_id=" + py_str_repr(expr_id()) + ")";
    }
    case NodeType::Var: {
      const auto& v = static_cast<const Var&>(*this);
      std::string tolerance = "None";
      if (const auto& bounds = v.tolerance(); bounds) {
        tolerance = "DimensionTolerance(lower_deviation=" + py_float_repr(bounds->lower_deviation()) +
                    ", upper_deviation=" + py_float_repr(bounds->upper_deviation()) + ")";
      }
      const auto& comment = v.comment();
      return "Var(name=" + py_str_repr(v.name()) + ", default=" + py_float_repr(v.default_value()) +
             ", comment=" + (comment ? py_str_repr(*comment) : "None") + ", expr_id=" + py_str_repr(expr_id()) +
             ", tolerance=" + tolerance + ", unit=" + optional_unit_repr(v.unit()) +
             ", tolerance_unit=" + optional_unit_repr(v.tolerance_unit()) + ")";
    }
    case NodeType::Expr: {
      const auto& e = static_cast<const Expr&>(*this);
      std::vector<std::string> items;
      for (const ScalarPtr& arg : e.args())
        items.push_back(arg->repr());
      return "Expr(op=" + py_str_repr(e.op()) + ", args=" + tuple_text(items) + ", expr_id=" + py_str_repr(expr_id()) +
             ")";
    }
  }
  return {};
}

// ---------------------------------------------------------------------------
// Const / Var / Expr
// ---------------------------------------------------------------------------

std::shared_ptr<const Const> Const::make(double value, std::string expr_id) {
  finite_scalar(value, "value");
  if (expr_id.empty())
    expr_id = structural_id("const", tuple_text({"'const'", hex_text(value)}));
  return std::make_shared<const Const>(Private{}, std::move(expr_id), value);
}

std::shared_ptr<const Var> Var::make(VarSpec spec) {
  if (spec.name.empty())
    throw ValueError("Variable name must be a non-empty string");
  finite_scalar(spec.default_value, "Variable default");
  if (!spec.unit && spec.tolerance_unit)
    throw ValueError("A tolerance unit requires a nominal variable unit");
  if (!spec.tolerance && spec.tolerance_unit)
    throw ValueError("A tolerance unit requires a declared tolerance");
  if (spec.tolerance && spec.unit) {
    if (!spec.tolerance_unit) {
      spec.tolerance_unit = spec.unit;
    } else if (spec.tolerance_unit->dimension() != spec.unit->dimension()) {
      throw ValueError("Variable tolerance unit must have the same dimension as its nominal unit");
    }
  }
  if (spec.unit)
    spec.unit->to_canonical(spec.default_value);
  if (spec.tolerance && spec.tolerance_unit) {
    DimensionTolerance(spec.tolerance_unit->to_canonical(spec.tolerance->lower_deviation()),
                       spec.tolerance_unit->to_canonical(spec.tolerance->upper_deviation()));
  }

  const Inference inference =
      spec.unit ? Inference{spec.unit->dimension(), true, false, false} : Inference{std::nullopt, false, true, false};
  std::string id = std::move(spec.expr_id);
  if (id.empty())
    id = structural_id("var", var_signature(spec));
  return std::make_shared<const Var>(Private{}, std::move(id), inference, std::move(spec));
}

double Var::canonical_default() const {
  return spec_.unit ? spec_.unit->to_canonical(spec_.default_value) : spec_.default_value;
}

std::optional<DimensionTolerance> Var::canonical_tolerance() const {
  if (!spec_.tolerance)
    return std::nullopt;
  if (!spec_.tolerance_unit)
    return spec_.tolerance;
  return DimensionTolerance(spec_.tolerance_unit->to_canonical(spec_.tolerance->lower_deviation()),
                            spec_.tolerance_unit->to_canonical(spec_.tolerance->upper_deviation()));
}

std::shared_ptr<const Var> Var::with_default(double value) const {
  VarSpec spec = spec_;
  spec.default_value = value;
  spec.expr_id.clear();
  return Var::make(std::move(spec));
}

double Var::eval_unchecked(const Bindings* bindings) const {
  if (bindings != nullptr) {
    const auto found = bindings->find(spec_.name);
    if (found != bindings->end()) {
      const double value = finite_scalar(found->second, "Binding '" + spec_.name + "'");
      return spec_.unit ? spec_.unit->to_canonical(value) : value;
    }
  }
  return canonical_default();
}

ParamSpec Var::param_spec() const {
  return make_param_spec(spec_.name, ParamKind::Float, Value(spec_.default_value), spec_.ui, "var",
                         spec_.unit ? std::optional<std::string>(spec_.unit->symbol()) : std::nullopt, spec_.comment);
}

namespace {

enum Opcode : int { kAdd, kSub, kMul, kDiv, kPow, kNeg, kAbs, kSin, kCos, kTan, kSqrt, kAcos, kAsin, kAtan, kAtan2 };

int opcode_of(std::string_view op) noexcept {
  static constexpr std::string_view kNames[] = {"add", "sub", "mul",  "div",  "pow",  "neg",  "abs",  "sin",
                                                "cos", "tan", "sqrt", "acos", "asin", "atan", "atan2"};
  for (std::size_t i = 0; i < std::size(kNames); ++i) {
    if (kNames[i] == op)
      return static_cast<int>(i);
  }
  return -1;
}

}  // namespace

Expr::Expr(Private, std::string id, Inference inference, std::exception_ptr error, std::string op,
           std::vector<ScalarPtr> args)
    : ScalarNode(std::move(id), inference, std::move(error)),
      op_(std::move(op)),
      args_(std::move(args)),
      opcode_(opcode_of(op_)) {}

std::size_t expr_op_arity(std::string_view op) noexcept {
  switch (opcode_of(op)) {
    case kAdd:
    case kSub:
    case kMul:
    case kDiv:
    case kPow:
    case kAtan2:
      return 2;
    case -1:
      return 0;
    default:
      return 1;
  }
}

std::shared_ptr<const Expr> Expr::make(std::string op, std::vector<ScalarPtr> args, std::string expr_id) {
  const std::size_t arity = expr_op_arity(op);
  if (arity == 0)
    throw ValueError("Unsupported expression op '" + op + "'");
  if (args.size() != arity) {
    throw ValueError("Expression op '" + op + "' expects " + std::to_string(arity) + " arguments, got " +
                     std::to_string(args.size()));
  }
  if (std::any_of(args.begin(), args.end(), [](const ScalarPtr& a) { return a == nullptr; })) {
    throw TypeError("Expression arguments must be scalar expression nodes");
  }
  Inference inference;
  std::exception_ptr error;
  try {
    inference = infer_expression(op, args);
  } catch (const std::exception&) {
    error = std::current_exception();
  }
  if (expr_id.empty()) {
    std::vector<std::string> ids;
    for (const ScalarPtr& arg : args)
      ids.push_back(py_str_repr(arg->expr_id()));
    expr_id = structural_id("expr", tuple_text({"'expr'", py_str_repr(op), tuple_text(ids)}));
  }
  return std::make_shared<const Expr>(Private{}, std::move(expr_id), inference, std::move(error), std::move(op),
                                      std::move(args));
}

double Expr::eval_unchecked(const Bindings* bindings) const {
  const double a = args_[0]->eval_unchecked(bindings);
  const double b = args_.size() > 1 ? args_[1]->eval_unchecked(bindings) : 0.0;
  const bool units = inference().typed;
  const auto angle_out = [units](double r) { return units ? degrees(r) : r; };
  switch (opcode_) {
    case kAdd:
      return a + b;
    case kSub:
      return a - b;
    case kMul:
      return a * b;
    case kDiv:
      if (b == 0.0)
        throw ValueError("float division by zero");
      return a / b;
    case kPow:
      return checked_pow(a, b);
    case kNeg:
      return -a;
    case kAbs:
      return std::fabs(a);
    case kSin:
      return std::sin(units ? radians(a) : a);
    case kCos:
      return std::cos(units ? radians(a) : a);
    case kTan:
      return std::tan(units ? radians(a) : a);
    case kSqrt:
      if (a < 0.0)
        throw ValueError("math domain error (sqrt)");
      return std::sqrt(a);
    case kAcos:
      return angle_out(std::acos(unit_domain(a, "acos")));
    case kAsin:
      return angle_out(std::asin(unit_domain(a, "asin")));
    case kAtan:
      return angle_out(std::atan(a));
    case kAtan2:
      return angle_out(std::atan2(a, b));
    default:
      break;
  }
  throw ValueError("Unsupported expression op '" + op_ + "'");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

std::shared_ptr<const Var> make_var(std::string name, double default_value, std::optional<std::string> comment,
                                    std::optional<DimensionTolerance> tolerance, std::optional<Unit> unit,
                                    std::optional<Unit> tolerance_unit, ParamUi ui) {
  VarSpec spec;
  spec.name = std::move(name);
  spec.default_value = default_value;
  spec.comment = std::move(comment);
  spec.tolerance = std::move(tolerance);
  spec.unit = std::move(unit);
  spec.tolerance_unit = std::move(tolerance_unit);
  spec.ui = std::move(ui);
  return Var::make(std::move(spec));
}

std::shared_ptr<const Const> make_const(double value) {
  finite_scalar(value, "Constant value");
  return Const::make(value);
}

const ScalarNode* scalar_node(const ExprPtr& expr) noexcept {
  return dynamic_cast<const ScalarNode*>(expr.get());
}
const ScalarNode* scalar_node(const Scalar& scalar) noexcept {
  return scalar_node(scalar.expr());
}

ScalarPtr lift_scalar(double value) {
  return Const::make(value);
}

ScalarPtr lift_scalar(const Scalar& scalar) {
  if (!scalar.symbolic())
    return Const::make(scalar.literal());
  if (auto node = std::dynamic_pointer_cast<const ScalarNode>(scalar.expr()))
    return node;
  throw TypeError("Unsupported expression node type: " + scalar.expr()->repr());
}

std::optional<Dimension> infer_dimension(const ScalarPtr& value) {
  return value->inference().dimension;
}
std::optional<Dimension> infer_dimension(const Scalar& value) {
  return lift_scalar(value)->inference().dimension;
}
bool expression_uses_units(const ScalarPtr& value) {
  return value->inference().typed;
}

std::vector<std::shared_ptr<const Var>> referenced_vars(const ScalarPtr& root) {
  std::vector<std::shared_ptr<const Var>> found;
  if (!root)
    return found;
  std::unordered_set<const ScalarNode*> seen;
  std::vector<const ScalarPtr*> stack{&root};
  while (!stack.empty()) {
    const ScalarPtr& node = *stack.back();
    stack.pop_back();
    if (!seen.insert(node.get()).second)
      continue;
    if (node->type() == NodeType::Var) {
      found.push_back(std::static_pointer_cast<const Var>(node));
    } else if (node->type() == NodeType::Expr) {
      const auto& args = static_cast<const Expr&>(*node).args();
      for (auto it = args.rbegin(); it != args.rend(); ++it)
        stack.push_back(&*it);
    }
  }
  // Operands are visited left to right (the stack reverses the push order).
  std::vector<std::shared_ptr<const Var>> unique;
  std::unordered_set<std::string> names;
  for (auto& v : found) {
    if (names.insert(v->expr_id()).second)
      unique.push_back(std::move(v));
  }
  return unique;
}

std::vector<std::shared_ptr<const Var>> referenced_vars(const Scalar& scalar) {
  if (!scalar.symbolic())
    return {};
  return referenced_vars(lift_scalar(scalar));
}

// ---------------------------------------------------------------------------
// Sym
// ---------------------------------------------------------------------------

Sym::Sym(double value) : node_(Const::make(value)) {}
Sym::Sym(int value) : node_(Const::make(static_cast<double>(value))) {}
Sym::Sym(ScalarPtr node) : node_(std::move(node)) {
  if (!node_)
    throw TypeError("Sym needs an expression node");
}
Sym::Sym(const Scalar& scalar) : node_(lift_scalar(scalar)) {}

namespace {
Sym binary(const char* op, const Sym& a, const Sym& b) {
  return Sym(Expr::make(op, {a.node(), b.node()}));
}
Sym unary(const char* op, const Sym& a) {
  return Sym(Expr::make(op, {a.node()}));
}
}  // namespace

Sym operator+(const Sym& a, const Sym& b) {
  return binary("add", a, b);
}
Sym operator-(const Sym& a, const Sym& b) {
  return binary("sub", a, b);
}
Sym operator*(const Sym& a, const Sym& b) {
  return binary("mul", a, b);
}
Sym operator/(const Sym& a, const Sym& b) {
  return binary("div", a, b);
}
Sym operator-(const Sym& a) {
  return unary("neg", a);
}
Sym pow(const Sym& base, const Sym& exponent) {
  return binary("pow", base, exponent);
}
Sym abs(const Sym& value) {
  return unary("abs", value);
}
Sym sin(const Sym& value) {
  return unary("sin", value);
}
Sym cos(const Sym& value) {
  return unary("cos", value);
}
Sym tan(const Sym& value) {
  return unary("tan", value);
}
Sym sqrt(const Sym& value) {
  return unary("sqrt", value);
}
Sym acos(const Sym& value) {
  return unary("acos", value);
}
Sym asin(const Sym& value) {
  return unary("asin", value);
}
Sym atan(const Sym& value) {
  return unary("atan", value);
}
Sym atan2(const Sym& y, const Sym& x) {
  return binary("atan2", y, x);
}

}  // namespace scad::reactive
