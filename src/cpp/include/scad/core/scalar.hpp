// Scalar: a number that may carry the expression it came from.
//
// Operators accept Scalar wherever the Python API accepts ScalarLike (a float,
// or a Var / Expr).  Evaluating always gives a double; the expression, when
// present, is what the reactive graph records so a parameter edit can rerun
// only the operations that depend on it.
#pragma once

#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

namespace scad {

// Name -> value overrides applied while evaluating expressions.
using Bindings = std::map<std::string, double, std::less<>>;

// Base of the expression tree.  The concrete nodes (Const, Var, Expr) live in
// scad/reactive/expr.hpp; operators only ever see this interface.
class ExprNode {
 public:
  virtual ~ExprNode() = default;
  virtual double eval(const Bindings* bindings) const = 0;
  virtual std::string repr() const = 0;
};

using ExprPtr = std::shared_ptr<const ExprNode>;

// The bindings an evaluation uses when it is handed none (Scalar::value with a
// null `bindings`).  The reactive Session installs its variable values here
// while it records, so an operator called after a parameter edit sees the
// edited value without every operator being passed the bindings.  Per thread;
// nullptr outside a scope.
const Bindings* ambient_bindings() noexcept;

// RAII: make `bindings` the ambient bindings of this thread (nests).  The
// pointee must outlive the scope.
class AmbientBindingsScope {
 public:
  explicit AmbientBindingsScope(const Bindings* bindings) noexcept;
  ~AmbientBindingsScope();
  AmbientBindingsScope(const AmbientBindingsScope&) = delete;
  AmbientBindingsScope& operator=(const AmbientBindingsScope&) = delete;

 private:
  const Bindings* previous_;
};

class Scalar {
 public:
  Scalar() = default;
  Scalar(double value) noexcept : value_(value) {}                    // NOLINT(google-explicit-constructor)
  Scalar(int value) noexcept : value_(static_cast<double>(value)) {}  // NOLINT(google-explicit-constructor)
  explicit Scalar(ExprPtr expr) : expr_(std::move(expr)) {}

  bool symbolic() const noexcept { return static_cast<bool>(expr_); }
  const ExprPtr& expr() const noexcept { return expr_; }

  // evaluate_scalar(): the number this scalar stands for right now.  Throws
  // ValueError when the result is NaN or infinite.
  double value(const Bindings* bindings = nullptr) const;

  // The literal, for a non-symbolic scalar; 0 for a symbolic one.
  double literal() const noexcept { return value_; }

 private:
  double value_ = 0.0;
  ExprPtr expr_;
};

// Evaluate with a label for the error message ("width" -> "width must be finite").
double evaluate_scalar(const Scalar& s, std::string_view label = "value", const Bindings* bindings = nullptr);

}  // namespace scad
