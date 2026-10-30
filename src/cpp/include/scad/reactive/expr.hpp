// Symbolic scalars: port of simplecadapi/params/expr.py.
//
// A model parameter is a `Var` (named, with a default, optional units,
// tolerance and editor metadata); arithmetic on vars builds an expression DAG
// of `Const` / `Var` / `Expr` nodes.  Operators accept `Scalar`, which can hold
// such a node; the recorder keeps it so that a later change of the variable
// can rerun just the operations that depend on it.
//
// Nodes are immutable and shared (`std::shared_ptr<const ...>`), so they can
// be used from any thread; building the same expression twice gives the same
// content-derived `expr_id` as the Python SDK does.  Dimension inference runs
// once, when a node is built, from the stored results of its operands: a
// physically inconsistent expression can still be *built* (as in Python) and
// reports its UnitValidationError when it is evaluated or inferred.
#pragma once

#include <exception>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/reactive/param_ui.hpp"
#include "scad/reactive/units.hpp"

namespace scad::reactive {

// Permitted lower and upper deviations from a nominal dimension.  Deviations
// are signed: lower <= 0 <= upper.
class DimensionTolerance {
 public:
  // ValueError when a deviation is not finite or has the wrong sign.
  DimensionTolerance(double lower_deviation, double upper_deviation);

  static DimensionTolerance symmetric(double deviation);

  double lower_deviation() const noexcept { return lower_; }
  double upper_deviation() const noexcept { return upper_; }
  double width() const noexcept { return upper_ - lower_; }

  bool operator==(const DimensionTolerance&) const = default;

  Value to_value() const;
  static DimensionTolerance from_value(const Value& payload);

 private:
  double lower_;
  double upper_;
};

// What dimension inference knows about a node.
struct Inference {
  std::optional<Dimension> dimension;  // nullopt: only legacy (unit-less) variables
  bool typed = false;                  // contains a variable with a declared unit
  bool legacy = false;                 // contains a variable without a unit
  bool constant = false;               // built from constants only
};

enum class NodeType { Const, Var, Expr };

// The three node types share an id and the inference result.
class ScalarNode : public ExprNode {
 public:
  virtual NodeType type() const noexcept = 0;
  const std::string& expr_id() const noexcept { return id_; }

  // Dimension inference result; throws the UnitValidationError (or the
  // ValueError of a constant exponent) the expression is inconsistent with.
  const Inference& inference() const {
    if (error_)
      std::rethrow_exception(error_);
    return inference_;
  }

  // evaluate(): validates the expression's dimensions, then computes.
  double eval(const Bindings* bindings) const final {
    if (error_)
      std::rethrow_exception(error_);
    return eval_unchecked(bindings);
  }
  virtual double eval_unchecked(const Bindings* bindings) const = 0;

  std::string repr() const override;

 protected:
  ScalarNode(std::string id, Inference inference, std::exception_ptr error)
      : id_(std::move(id)), inference_(inference), error_(std::move(error)) {}

 private:
  std::string id_;
  Inference inference_;
  std::exception_ptr error_;
};

using ScalarPtr = std::shared_ptr<const ScalarNode>;

class Const final : public ScalarNode {
  struct Private {
    explicit Private() = default;
  };

 public:
  // ValueError when `value` is not finite.  An empty id is derived from the content.
  static std::shared_ptr<const Const> make(double value, std::string expr_id = {});

  Const(Private, std::string id, double value)
      : ScalarNode(std::move(id), constant_inference(), nullptr), value_(value) {}

  NodeType type() const noexcept override { return NodeType::Const; }
  double value() const noexcept { return value_; }
  double eval_unchecked(const Bindings*) const override { return value_; }

 private:
  static Inference constant_inference() { return {kDimensionless, false, false, true}; }
  double value_;
};

struct VarSpec {
  std::string name;
  double default_value = 0.0;
  std::optional<std::string> comment;
  std::optional<DimensionTolerance> tolerance;
  std::optional<Unit> unit;
  std::optional<Unit> tolerance_unit;  // defaults to `unit` when a tolerance is declared
  std::string expr_id;                 // empty: derived from the content
  ParamUi ui;                          // editor metadata; not part of the identity
};

// A named scalar parameter.  `default_value` and `tolerance` stay in their
// declared units; evaluation converts them to the canonical CAD units
// (millimeters for length, degrees for angle).
class Var final : public ScalarNode {
  struct Private {
    explicit Private() = default;
  };

 public:
  static std::shared_ptr<const Var> make(VarSpec spec);

  Var(Private, std::string id, Inference inference, VarSpec spec)
      : ScalarNode(std::move(id), inference, nullptr), spec_(std::move(spec)) {}

  NodeType type() const noexcept override { return NodeType::Var; }
  const std::string& name() const noexcept { return spec_.name; }
  double default_value() const noexcept { return spec_.default_value; }
  const std::optional<std::string>& comment() const noexcept { return spec_.comment; }
  const std::optional<DimensionTolerance>& tolerance() const noexcept { return spec_.tolerance; }
  const std::optional<Unit>& unit() const noexcept { return spec_.unit; }
  const std::optional<Unit>& tolerance_unit() const noexcept { return spec_.tolerance_unit; }
  const ParamUi& ui() const noexcept { return spec_.ui; }
  const VarSpec& spec() const noexcept { return spec_; }

  std::optional<Dimension> dimension() const {
    return spec_.unit ? std::optional(spec_.unit->dimension()) : std::nullopt;
  }
  double canonical_default() const;
  std::optional<DimensionTolerance> canonical_tolerance() const;

  // The same variable with another default (runtime.params._replace): units,
  // tolerance, comment and editor metadata stay, the id is derived anew.
  std::shared_ptr<const Var> with_default(double value) const;

  double eval_unchecked(const Bindings* bindings) const override;

  // The editor's description of this variable.
  ParamSpec param_spec() const;

 private:
  VarSpec spec_;
};

class Expr final : public ScalarNode {
  struct Private {
    explicit Private() = default;
  };

 public:
  // ValueError for an unsupported op or a wrong number of operands.
  static std::shared_ptr<const Expr> make(std::string op, std::vector<ScalarPtr> args, std::string expr_id = {});

  Expr(Private, std::string id, Inference inference, std::exception_ptr error, std::string op,
       std::vector<ScalarPtr> args);

  NodeType type() const noexcept override { return NodeType::Expr; }
  const std::string& op() const noexcept { return op_; }
  const std::vector<ScalarPtr>& args() const noexcept { return args_; }
  double eval_unchecked(const Bindings* bindings) const override;

 private:
  std::string op_;
  std::vector<ScalarPtr> args_;
  int opcode_;  // index of op_ in the evaluator's table
};

// The ops an Expr can carry and how many operands each takes (0: unsupported).
std::size_t expr_op_arity(std::string_view op) noexcept;

// ---------------------------------------------------------------------------
// Construction helpers
// ---------------------------------------------------------------------------

// Variable.  ValueError for an empty name or a non-finite default.
std::shared_ptr<const Var> make_var(std::string name, double default_value,
                                    std::optional<std::string> comment = std::nullopt,
                                    std::optional<DimensionTolerance> tolerance = std::nullopt,
                                    std::optional<Unit> unit = std::nullopt,
                                    std::optional<Unit> tolerance_unit = std::nullopt, ParamUi ui = {});
std::shared_ptr<const Const> make_const(double value);

// lift_scalar: a literal becomes a Const, a symbolic Scalar keeps its node.
// TypeError when the Scalar holds a node this library did not make.
ScalarPtr lift_scalar(const Scalar& scalar);
ScalarPtr lift_scalar(double value);

// The node of a symbolic Scalar, or nullptr (a literal, or a foreign node).
const ScalarNode* scalar_node(const Scalar& scalar) noexcept;
const ScalarNode* scalar_node(const ExprPtr& expr) noexcept;

// ---------------------------------------------------------------------------
// Dimension inference
// ---------------------------------------------------------------------------

// The result dimension of an expression, nullopt for legacy (unit-less)
// expressions.  UnitValidationError when it is physically inconsistent.
std::optional<Dimension> infer_dimension(const ScalarPtr& value);
std::optional<Dimension> infer_dimension(const Scalar& value);
// Whether the expression contains a variable with a declared unit.
bool expression_uses_units(const ScalarPtr& value);

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

// The text a node's content hash is computed over (Python's _expr_signature).
// Two nodes with one id must have one signature.
std::string expr_signature(const ScalarNode& node);

// Structural equality (dataclass ==): same type and fields, operands compared
// recursively, ids included.
bool same_expression(const ScalarNode& a, const ScalarNode& b);

// Every variable the expression refers to, once each, in first-use order.
std::vector<std::shared_ptr<const Var>> referenced_vars(const ScalarPtr& root);
std::vector<std::shared_ptr<const Var>> referenced_vars(const Scalar& scalar);

// ---------------------------------------------------------------------------
// Handle with operators
// ---------------------------------------------------------------------------

// A value-semantics handle on an expression, for writing formulas in C++:
//
//     Sym w = make_var("w", 10.0, "width");
//     Scalar depth = (w * 2 + 1).scalar();
//
// A bare number is a constant; operators lift both sides.
class Sym {
 public:
  Sym(double value);    // NOLINT(google-explicit-constructor)
  Sym(int value);       // NOLINT(google-explicit-constructor)
  Sym(ScalarPtr node);  // NOLINT(google-explicit-constructor)
  // A Var, Const or Expr straight from its factory.
  template <class Node>
    requires std::is_base_of_v<ScalarNode, Node>
  Sym(std::shared_ptr<const Node> node) : Sym(ScalarPtr(std::move(node))) {}  // NOLINT(google-explicit-constructor)
  Sym(const Scalar& scalar);                                                  // NOLINT(google-explicit-constructor)

  const ScalarPtr& node() const noexcept { return node_; }
  Scalar scalar() const { return Scalar(ExprPtr(node_)); }
  operator Scalar() const { return scalar(); }  // NOLINT(google-explicit-constructor)

  // evaluate(): defaults unless `bindings` overrides a variable.
  double value(const Bindings* bindings = nullptr) const { return node_->eval(bindings); }
  const std::string& expr_id() const noexcept { return node_->expr_id(); }

 private:
  ScalarPtr node_;
};

Sym operator+(const Sym& a, const Sym& b);
Sym operator-(const Sym& a, const Sym& b);
Sym operator*(const Sym& a, const Sym& b);
Sym operator/(const Sym& a, const Sym& b);
Sym operator-(const Sym& a);
Sym pow(const Sym& base, const Sym& exponent);
Sym abs(const Sym& value);
Sym sin(const Sym& value);
Sym cos(const Sym& value);
Sym tan(const Sym& value);
Sym sqrt(const Sym& value);
Sym acos(const Sym& value);
Sym asin(const Sym& value);
Sym atan(const Sym& value);
Sym atan2(const Sym& y, const Sym& x);

}  // namespace scad::reactive
