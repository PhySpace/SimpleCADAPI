#include "scad/core/tolerance.hpp"
#include "scad/reactive/bspline_fit.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>

#include "scad/core/error.hpp"

namespace scad::reactive {

namespace {

constexpr int kDegree = 3;
constexpr double kKnotMergeTolerance = tol::kDuplicateParameter;

// Dense row-major matrix.
struct Matrix {
  std::size_t rows = 0, cols = 0;
  std::vector<double> data;

  Matrix() = default;
  Matrix(std::size_t r, std::size_t c) : rows(r), cols(c), data(r * c, 0.0) {}
  double& at(std::size_t r, std::size_t c) { return data[r * cols + c]; }
  double at(std::size_t r, std::size_t c) const { return data[r * cols + c]; }
};

// Minimum-norm least squares, as numpy.linalg.lstsq(rcond=None): one-sided Jacobi SVD,
// singular values below eps * max(m, n) * sigma_max are dropped.
Matrix least_squares(Matrix a, const Matrix& b) {
  const std::size_t m = a.rows, n = a.cols;
  Matrix v(n, n);
  for (std::size_t i = 0; i < n; ++i)
    v.at(i, i) = 1.0;
  constexpr double eps = std::numeric_limits<double>::epsilon();
  for (int sweep = 0; sweep < 60; ++sweep) {
    bool rotated = false;
    for (std::size_t p = 0; p + 1 < n; ++p) {
      for (std::size_t q = p + 1; q < n; ++q) {
        double alpha = 0, beta = 0, gamma = 0;
        for (std::size_t i = 0; i < m; ++i) {
          alpha += a.at(i, p) * a.at(i, p);
          beta += a.at(i, q) * a.at(i, q);
          gamma += a.at(i, p) * a.at(i, q);
        }
        if (gamma == 0.0 || std::fabs(gamma) <= eps * std::sqrt(alpha * beta))
          continue;
        rotated = true;
        const double zeta = (beta - alpha) / (2.0 * gamma);
        const double t = (zeta >= 0 ? 1.0 : -1.0) / (std::fabs(zeta) + std::sqrt(1.0 + zeta * zeta));
        const double c = 1.0 / std::sqrt(1.0 + t * t), s = c * t;
        for (std::size_t i = 0; i < m; ++i) {
          const double x = a.at(i, p), y = a.at(i, q);
          a.at(i, p) = c * x - s * y;
          a.at(i, q) = s * x + c * y;
        }
        for (std::size_t i = 0; i < n; ++i) {
          const double x = v.at(i, p), y = v.at(i, q);
          v.at(i, p) = c * x - s * y;
          v.at(i, q) = s * x + c * y;
        }
      }
    }
    if (!rotated)
      break;
  }
  std::vector<double> sigma(n);
  double sigma_max = 0.0;
  for (std::size_t j = 0; j < n; ++j) {
    double sum = 0.0;
    for (std::size_t i = 0; i < m; ++i)
      sum += a.at(i, j) * a.at(i, j);
    sigma[j] = std::sqrt(sum);
    sigma_max = std::max(sigma_max, sigma[j]);
  }
  const double cutoff = eps * static_cast<double>(std::max(m, n)) * sigma_max;
  Matrix x(n, b.cols);
  for (std::size_t j = 0; j < n; ++j) {
    if (sigma[j] <= cutoff || sigma[j] == 0.0)
      continue;
    for (std::size_t k = 0; k < b.cols; ++k) {
      double projection = 0.0;  // (u_j . b_k) / sigma_j, u_j = a_j / sigma_j
      for (std::size_t i = 0; i < m; ++i)
        projection += a.at(i, j) * b.at(i, k);
      projection /= sigma[j] * sigma[j];
      for (std::size_t i = 0; i < n; ++i)
        x.at(i, k) += projection * v.at(i, j);
    }
  }
  return x;
}

using Point = std::vector<double>;

std::vector<double> full_knot_vector(int degree, const std::vector<double>& interior) {
  std::vector<double> sorted = interior;
  std::sort(sorted.begin(), sorted.end());
  std::vector<double> knots(static_cast<std::size_t>(degree) + 1, 0.0);
  knots.insert(knots.end(), sorted.begin(), sorted.end());
  knots.insert(knots.end(), static_cast<std::size_t>(degree) + 1, 1.0);
  return knots;
}

std::vector<double> validate_interior_knots(std::vector<double> knots, double knot_tolerance) {
  std::sort(knots.begin(), knots.end());
  std::vector<double> out;
  for (const double knot : knots) {
    if (!std::isfinite(knot))
      throw ValueError("adaptive knot values must be finite");
    if (knot <= knot_tolerance || knot >= 1.0 - knot_tolerance)
      continue;
    if (!out.empty() && std::fabs(knot - out.back()) <= knot_tolerance)
      continue;
    out.push_back(knot);
  }
  return out;
}

std::vector<double> basis_row(double parameter, int degree, const std::vector<double>& knots) {
  const int control_count = static_cast<int>(knots.size()) - degree - 1;
  if (control_count <= 0)
    throw ValueError("invalid knot vector/control count combination");
  const auto d = static_cast<std::size_t>(degree);
  const double last = knots[knots.size() - d - 1];
  const double u = std::min(std::max(parameter, knots[d]), last);
  if (u >= last) {
    std::vector<double> row(static_cast<std::size_t>(control_count), 0.0);
    row.back() = 1.0;
    return row;
  }
  std::vector<double> active(knots.size() - 1, 0.0);
  for (std::size_t i = 0; i < active.size(); ++i) {
    if (knots[i] <= u && u < knots[i + 1])
      active[i] = 1.0;
  }
  for (std::size_t current = 1; current <= d; ++current) {
    std::vector<double> next(knots.size() - 1 - current, 0.0);
    for (std::size_t i = 0; i < next.size(); ++i) {
      const double left_den = knots[i + current] - knots[i];
      const double right_den = knots[i + current + 1] - knots[i + 1];
      double left = 0.0, right = 0.0;
      if (left_den > 0.0)
        left = (u - knots[i]) / left_den * active[i];
      if (right_den > 0.0)
        right = (knots[i + current + 1] - u) / right_den * active[i + 1];
      next[i] = left + right;
    }
    active = std::move(next);
  }
  active.resize(static_cast<std::size_t>(control_count));
  return active;
}

Matrix basis_matrix(const std::vector<double>& parameters, int degree, const std::vector<double>& knots) {
  Matrix out(parameters.size(), static_cast<std::size_t>(static_cast<int>(knots.size()) - degree - 1));
  for (std::size_t r = 0; r < parameters.size(); ++r) {
    const std::vector<double> row = basis_row(parameters[r], degree, knots);
    for (std::size_t c = 0; c < row.size(); ++c)
      out.at(r, c) = row[c];
  }
  return out;
}

double distance(const Point& a, const Point& b) {
  double sum = 0.0;
  for (std::size_t i = 0; i < a.size(); ++i)
    sum += (a[i] - b[i]) * (a[i] - b[i]);
  return std::sqrt(sum);
}

// Rows of `controls` mapped through the basis: basis @ controls.
std::vector<Point> evaluate_basis(const Matrix& basis, const std::vector<Point>& controls) {
  const std::size_t dimension = controls.empty() ? 0 : controls.front().size();
  std::vector<Point> out(basis.rows, Point(dimension, 0.0));
  for (std::size_t r = 0; r < basis.rows; ++r) {
    for (std::size_t c = 0; c < basis.cols; ++c) {
      const double w = basis.at(r, c);
      if (w == 0.0)
        continue;
      for (std::size_t k = 0; k < dimension; ++k)
        out[r][k] += w * controls[c][k];
    }
  }
  return out;
}

std::vector<double> errors_of(const std::vector<Point>& fitted, const std::vector<Point>& points) {
  std::vector<double> errors;
  errors.reserve(points.size());
  for (std::size_t i = 0; i < points.size(); ++i)
    errors.push_back(distance(fitted[i], points[i]));
  return errors;
}

double max_of(const std::vector<double>& values) {
  return values.empty() ? 0.0 : *std::max_element(values.begin(), values.end());
}

double rms_of(const std::vector<double>& values) {
  if (values.empty())
    return 0.0;
  double sum = 0.0;
  for (const double v : values)
    sum += v * v;
  return std::sqrt(sum / static_cast<double>(values.size()));
}

std::vector<Point> clean_samples(const std::vector<Point>& raw, double duplicate_tolerance) {
  if (duplicate_tolerance < 0.0 || !std::isfinite(duplicate_tolerance)) {
    throw ValueError("duplicate_tolerance must be a finite non-negative number");
  }
  if (raw.empty())
    throw ValueError("sample_points must contain at least two distinct points");
  std::size_t dimension = 0;
  for (std::size_t index = 0; index < raw.size(); ++index) {
    if (index == 0) {
      dimension = raw[0].size();
      if (dimension != 2 && dimension != 3)
        throw ValueError("sample points must be 2D or 3D");
    } else if (raw[index].size() != dimension) {
      throw ValueError("all sample points must have the same dimension");
    }
    for (const double value : raw[index]) {
      if (!std::isfinite(value))
        throw ValueError("all sample point coordinates must be finite");
    }
  }
  std::vector<Point> out;
  for (const Point& point : raw) {
    if (!out.empty() && distance(point, out.back()) <= duplicate_tolerance)
      continue;
    out.push_back(point);
  }
  if (out.size() < 2)
    throw ValueError("sample_points must contain at least two distinct points");
  return out;
}

std::vector<double> chord_length_parameters(const std::vector<Point>& points) {
  std::vector<double> parameters{0.0};
  double total = 0.0;
  for (std::size_t i = 1; i < points.size(); ++i) {
    total += distance(points[i], points[i - 1]);
    parameters.push_back(total);
  }
  if (total <= 0.0 || !std::isfinite(total))
    throw ValueError("sample_points must span a non-zero chord length");
  for (double& p : parameters)
    p /= total;
  parameters.back() = 1.0;
  return parameters;
}

BSplineFit result_from(const std::vector<Point>& controls, const std::vector<double>& knots,
                       const std::vector<double>& parameters, const std::vector<Point>& points, double tolerance,
                       double fairing, int iterations) {
  const Matrix basis = basis_matrix(parameters, kDegree, knots);
  const std::vector<double> errors = errors_of(evaluate_basis(basis, controls), points);
  BSplineFit fit;
  fit.degree = kDegree;
  fit.control_points = controls;
  fit.knots = knots;
  fit.sample_parameters = parameters;
  fit.max_error = max_of(errors);
  fit.rms_error = rms_of(errors);
  fit.tolerance = tolerance;
  fit.fairing = fairing;
  fit.iterations = iterations;
  fit.converged = fit.max_error <= tolerance;
  return fit;
}

BSplineFit straight_line_result(const std::vector<Point>& points, const std::vector<double>& parameters,
                                double tolerance, double fairing) {
  const Point& start = points.front();
  const Point& end = points.back();
  std::vector<Point> controls(4, Point(start.size()));
  for (std::size_t k = 0; k < start.size(); ++k) {
    const double delta = end[k] - start[k];
    controls[0][k] = start[k];
    controls[1][k] = start[k] + delta / 3.0;
    controls[2][k] = start[k] + 2.0 * delta / 3.0;
    controls[3][k] = end[k];
  }
  BSplineFit fit = result_from(controls, full_knot_vector(kDegree, {}), parameters, points, tolerance, fairing, 0);
  fit.converged = true;  // the Python result is converged by construction; the caller checks max_error
  return fit;
}

BSplineFit fit_for_knots(const std::vector<Point>& points, const std::vector<double>& parameters,
                         const std::vector<double>& interior_knots, double fairing, double tolerance, int iterations) {
  const std::vector<double> knots = full_knot_vector(kDegree, interior_knots);
  const Matrix basis = basis_matrix(parameters, kDegree, knots);
  const std::size_t control_count = basis.cols;
  const std::size_t dimension = points.front().size();

  std::vector<Point> controls(control_count, Point(dimension, 0.0));
  controls.front() = points.front();
  controls.back() = points.back();

  const std::size_t unknowns = control_count >= 2 ? control_count - 2 : 0;
  if (unknowns > 0) {
    // Unknown control i (1 .. count-2) is column i-1.
    const std::size_t samples = points.size();
    const std::size_t fairing_rows = fairing > 0.0 ? control_count - 2 : 0;
    Matrix matrix(samples + fairing_rows, unknowns);
    Matrix rhs(samples + fairing_rows, dimension);
    for (std::size_t r = 0; r < samples; ++r) {
      for (std::size_t c = 0; c < unknowns; ++c)
        matrix.at(r, c) = basis.at(r, c + 1);
      for (std::size_t k = 0; k < dimension; ++k) {
        rhs.at(r, k) =
            points[r][k] - basis.at(r, 0) * controls.front()[k] - basis.at(r, control_count - 1) * controls.back()[k];
      }
    }
    if (fairing_rows > 0) {
      const double scale = std::sqrt(fairing);
      for (std::size_t start = 0; start < fairing_rows; ++start) {
        const std::size_t row = samples + start;
        const std::size_t indices[3] = {start, start + 1, start + 2};
        const double coefficients[3] = {1.0, -2.0, 1.0};
        for (int t = 0; t < 3; ++t) {
          const std::size_t control_index = indices[t];
          if (control_index == 0 || control_index == control_count - 1) {
            const Point& fixed = controls[control_index];
            for (std::size_t k = 0; k < dimension; ++k)
              rhs.at(row, k) -= coefficients[t] * fixed[k] * scale;
          } else {
            matrix.at(row, control_index - 1) += coefficients[t] * scale;
          }
        }
      }
    }
    const Matrix solved = least_squares(std::move(matrix), rhs);
    for (std::size_t i = 0; i < unknowns; ++i) {
      for (std::size_t k = 0; k < dimension; ++k)
        controls[i + 1][k] = solved.at(i, k);
    }
  }
  return result_from(controls, knots, parameters, points, tolerance, fairing, iterations);
}

std::vector<double> insert_adaptive_knot(const std::vector<double>& interior, const std::vector<double>& parameters,
                                         const std::vector<double>& errors, double knot_tolerance) {
  const std::vector<double> current = validate_interior_knots(interior, knot_tolerance);
  std::vector<double> boundaries{0.0};
  boundaries.insert(boundaries.end(), current.begin(), current.end());
  boundaries.push_back(1.0);

  struct Span {
    double left, right;
    long local_index;
    double error;
  };
  std::optional<Span> best;
  for (std::size_t s = 0; s + 1 < boundaries.size(); ++s) {
    const double left = boundaries[s], right = boundaries[s + 1];
    if (right - left <= 2.0 * knot_tolerance)
      continue;
    long local_index = -1;
    double span_error = -1.0;
    for (std::size_t i = 0; i < parameters.size(); ++i) {
      if (!(parameters[i] > left + knot_tolerance && parameters[i] < right - knot_tolerance))
        continue;
      if (local_index < 0 || errors[i] > span_error) {  // first maximum, like argmax
        local_index = static_cast<long>(i);
        span_error = errors[i];
      }
    }
    if (!best || span_error > best->error ||
        (span_error == best->error && (right - left) > (best->right - best->left))) {
      best = Span{left, right, local_index, span_error};
    }
  }
  if (!best)
    return current;

  double candidate = best->local_index >= 0 ? parameters[static_cast<std::size_t>(best->local_index)]
                                            : 0.5 * (best->left + best->right);
  candidate = std::min(std::max(candidate, best->left + knot_tolerance), best->right - knot_tolerance);
  const auto near_existing = [&](double value) {
    return std::any_of(current.begin(), current.end(),
                       [&](double knot) { return std::fabs(value - knot) <= knot_tolerance; });
  };
  if (near_existing(candidate))
    candidate = 0.5 * (best->left + best->right);
  if (candidate <= knot_tolerance || candidate >= 1.0 - knot_tolerance)
    candidate = 0.5 * (best->left + best->right);
  if (near_existing(candidate)) {
    std::vector<std::pair<double, double>> spans;
    for (std::size_t s = 0; s + 1 < boundaries.size(); ++s)
      spans.emplace_back(boundaries[s], boundaries[s + 1]);
    std::stable_sort(spans.begin(), spans.end(),
                     [](const auto& a, const auto& b) { return a.second - a.first > b.second - b.first; });
    for (const auto& [left, right] : spans) {
      if (right - left > 2.0 * knot_tolerance) {
        candidate = 0.5 * (left + right);
        break;
      }
    }
  }
  std::vector<double> next = current;
  next.push_back(candidate);
  return validate_interior_knots(std::move(next), knot_tolerance);
}

BSplineFit prune_knots(const std::vector<Point>& points, const std::vector<double>& parameters,
                       const std::vector<double>& interior, double fairing, double tolerance, double knot_tolerance,
                       int iterations) {
  std::vector<double> current = validate_interior_knots(interior, knot_tolerance);
  BSplineFit current_result = fit_for_knots(points, parameters, current, fairing, tolerance, iterations);
  bool changed = true;
  while (changed && !current.empty()) {
    changed = false;
    std::optional<std::pair<std::vector<double>, BSplineFit>> best;
    for (std::size_t index = 0; index < current.size(); ++index) {
      std::vector<double> candidate = current;
      candidate.erase(candidate.begin() + static_cast<std::ptrdiff_t>(index));
      BSplineFit result = fit_for_knots(points, parameters, candidate, fairing, tolerance, iterations);
      if (result.max_error <= tolerance && (!best || result.max_error < best->second.max_error)) {
        best.emplace(std::move(candidate), std::move(result));
      }
    }
    if (best) {
      current = std::move(best->first);
      current_result = std::move(best->second);
      changed = true;
    }
  }
  return current_result;
}

std::string general(double value) {
  char buf[32];
  std::snprintf(buf, sizeof buf, "%g", value);
  return buf;
}

}  // namespace

std::vector<double> BSplineFit::unique_knots() const {
  std::vector<double> unique;
  for (const double knot : knots) {
    if (unique.empty() || std::fabs(knot - unique.back()) > kKnotMergeTolerance)
      unique.push_back(knot);
  }
  return unique;
}

std::vector<int> BSplineFit::multiplicities() const {
  std::vector<int> out;
  if (knots.empty())
    return out;
  double current = knots.front();
  int count = 0;
  for (const double knot : knots) {
    if (std::fabs(knot - current) <= kKnotMergeTolerance) {
      ++count;
      continue;
    }
    out.push_back(count);
    current = knot;
    count = 1;
  }
  out.push_back(count);
  return out;
}

std::vector<double> BSplineFit::evaluate(double parameter) const {
  const std::vector<double> row = basis_row(parameter, degree, knots);
  std::vector<double> point(dimension(), 0.0);
  for (std::size_t i = 0; i < row.size(); ++i) {
    for (std::size_t k = 0; k < point.size(); ++k)
      point[k] += row[i] * control_points[i][k];
  }
  return point;
}

Value BSplineFit::to_value() const {
  const auto numbers = [](const std::vector<double>& values) {
    Value out = Value::array();
    for (const double v : values)
      out.push_back(v);
    return out;
  };
  Value out = Value::object();
  out.set("degree", degree);
  Value controls = Value::array();
  for (const auto& point : control_points)
    controls.push_back(numbers(point));
  out.set("control_points", std::move(controls));
  out.set("knots", numbers(knots));
  out.set("unique_knots", numbers(unique_knots()));
  Value mult = Value::array();
  for (const int m : multiplicities())
    mult.push_back(m);
  out.set("multiplicities", std::move(mult));
  out.set("sample_parameters", numbers(sample_parameters));
  out.set("max_error", max_error);
  out.set("rms_error", rms_error);
  out.set("tolerance", tolerance);
  out.set("fairing", fairing);
  out.set("iterations", iterations);
  out.set("converged", converged);
  return out;
}

BSplineFit fit_cubic_bspline_control_points(const std::vector<std::vector<double>>& sample_points,
                                            const BSplineFitOptions& options) {
  const double tolerance = options.tolerance, fairing = options.fairing, knot_tolerance = options.knot_tolerance;
  if (tolerance <= 0.0 || !std::isfinite(tolerance))
    throw ValueError("tolerance must be a finite positive number");
  if (fairing < 0.0 || !std::isfinite(fairing))
    throw ValueError("fairing must be a finite non-negative number");
  if (knot_tolerance <= 0.0 || !std::isfinite(knot_tolerance)) {
    throw ValueError("knot_tolerance must be a finite positive number");
  }

  const std::vector<Point> points = clean_samples(sample_points, options.duplicate_tolerance);
  const std::vector<double> parameters = chord_length_parameters(points);

  if (points.size() == 2) {
    BSplineFit result = straight_line_result(points, parameters, tolerance, fairing);
    if (result.max_error <= tolerance || !options.raise_on_failure)
      return result;
    throw ValueError("failed to fit a straight cubic B-spline within tolerance");
  }

  const int default_max = std::max(kDegree + 1, static_cast<int>(points.size()));
  const int max_controls = options.max_control_points.value_or(default_max);
  if (max_controls < kDegree + 1)
    throw ValueError("max_control_points must be at least 4 for a cubic B-spline");

  std::vector<double> interior_knots;
  std::optional<BSplineFit> best;
  const int max_insertions = max_controls - (kDegree + 1);
  for (int iteration = 0; iteration <= max_insertions; ++iteration) {
    BSplineFit result = fit_for_knots(points, parameters, interior_knots, fairing, tolerance, iteration);
    if (!best || result.max_error < best->max_error)
      best = result;
    if (result.max_error <= tolerance) {
      return prune_knots(points, parameters, interior_knots, fairing, tolerance, knot_tolerance, iteration);
    }
    if (iteration >= max_insertions)
      break;

    const Matrix basis = basis_matrix(parameters, kDegree, result.knots);
    const std::vector<double> errors = errors_of(evaluate_basis(basis, result.control_points), points);
    std::vector<double> next = insert_adaptive_knot(interior_knots, parameters, errors, knot_tolerance);
    if (next.size() == interior_knots.size())
      break;
    interior_knots = std::move(next);
  }

  if (!options.raise_on_failure) {
    best->converged = false;
    return *best;
  }
  throw ValueError("failed to fit a cubic B-spline within tolerance " + general(tolerance) + "; best max_error=" +
                   general(best->max_error) + " with " + std::to_string(best->control_count()) + " control points");
}

}  // namespace scad::reactive
