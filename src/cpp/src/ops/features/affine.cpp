// scale_rsolid, transform_rsolid (operators/transform.py).
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Trsf.hxx>

#include <algorithm>
#include <array>
#include <cmath>

#include "internal.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/ops/features/transforms.hpp"

namespace scad {

namespace {

using Mat3 = std::array<std::array<double, 3>, 3>;

Mat3 multiply(const Mat3& a, const Mat3& b) {
  Mat3 out{};
  for (std::size_t i = 0; i < 3; ++i)
    for (std::size_t j = 0; j < 3; ++j)
      for (std::size_t k = 0; k < 3; ++k)
        out[i][j] += a[i][k] * b[k][j];
  return out;
}

Mat3 transposed(const Mat3& m) {
  Mat3 out{};
  for (std::size_t i = 0; i < 3; ++i)
    for (std::size_t j = 0; j < 3; ++j)
      out[i][j] = m[j][i];
  return out;
}

Vec3 apply(const Mat3& m, const Vec3& v) {
  return {m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z, m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
          m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z};
}

double determinant(const Mat3& m) {
  return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
         m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
}

// The current coordinate system's axes as the columns of a matrix.
Mat3 current_basis() {
  const CoordinateSystem& cs = current_cs();
  const Vec3 x = cs.transform_vector({1, 0, 0}), y = cs.transform_vector({0, 1, 0}), z = cs.transform_vector({0, 0, 1});
  return {{{x.x, y.x, z.x}, {x.y, y.y, z.y}, {x.z, y.z, z.z}}};
}

// A general (affine) transformation of a solid.  The kernel's GTransform copies topology but can
// keep curve geometry shared with the boolean / fillet history that built the solid; isolating it
// first avoids invalid p-curves (and a crash in the checker) in OCCT 7.9.
TopoDS_Shape general_transform(const TopoDS_Shape& solid, const Mat3& linear, const Vec3& translation,
                               const char* failure) {
  return occt_guard([&]() -> TopoDS_Shape {
    gp_GTrsf transform;
    for (int row = 0; row < 3; ++row) {
      for (int col = 0; col < 3; ++col)
        transform.SetValue(row + 1, col + 1, linear[static_cast<std::size_t>(row)][static_cast<std::size_t>(col)]);
    }
    transform.SetValue(1, 4, translation.x);
    transform.SetValue(2, 4, translation.y);
    transform.SetValue(3, 4, translation.z);
    const TopoDS_Shape copied = BRepBuilderAPI_Copy(solid, true, false).Shape();
    BRepBuilderAPI_GTransform builder(copied, transform, true);
    builder.Build();
    if (!builder.IsDone())
      throw ValueError(failure);
    return builder.Shape();
  });
}

}  // namespace

Solid scale_rsolid(const Solid& solid, const Scalar3& factors, const Scalar3& center) {
  const Vec3 values = finite_vector(factors, "factors");
  const Vec3 center_value = finite_vector(center, "center");
  if (values.x == 0 || values.y == 0 || values.z == 0)
    throw ValueError("scale factors must be nonzero");
  const Vec3 global_center = features_detail::place_point(center_value);

  TopoDS_Shape scaled;
  if (values.x == values.y && values.y == values.z) {
    scaled = occt_guard([&]() -> TopoDS_Shape {
      gp_Trsf transform;
      transform.SetScale(kernel::to_pnt(global_center), values.x);
      BRepBuilderAPI_Transform builder(solid.wrapped(), transform, true);
      builder.Build();
      if (!builder.IsDone())
        throw ValueError("kernel could not scale the solid");
      return builder.Shape();
    });
  } else {
    const Mat3 basis = current_basis();
    const Mat3 diagonal{{{values.x, 0, 0}, {0, values.y, 0}, {0, 0, values.z}}};
    const Mat3 matrix = multiply(multiply(basis, diagonal), transposed(basis));
    scaled = general_transform(solid.wrapped(), matrix, global_center - apply(matrix, global_center),
                               "kernel could not scale the solid");
  }

  FeatureRecord rec("make_scale_rsolid");
  rec.point("factors", factors);
  rec.point("center", center);
  rec.input(solid, "body");
  return finish_solid(solid, scaled, std::move(rec).take());
}

Solid transform_rsolid(const Solid& solid, const std::vector<std::vector<Scalar>>& matrix) {
  // Shape and finiteness first: the numbers are read from the evaluated expressions.
  FeatureRecord rec("make_transform_rsolid");
  const std::vector<std::vector<double>> values = rec.matrix("matrix", matrix);
  const bool shaped =
      values.size() == 4 && std::all_of(values.begin(), values.end(), [](const auto& row) { return row.size() == 4; });
  if (!shaped)
    throw ValueError("matrix must be a finite 4x4 affine matrix");
  for (const auto& row : values) {
    for (const double v : row) {
      if (!std::isfinite(v))
        throw ValueError("matrix must be a finite 4x4 affine matrix");
    }
  }
  const std::array<double, 4> last{0, 0, 0, 1};
  for (std::size_t j = 0; j < 4; ++j) {
    if (std::abs(values[3][j] - last[j]) > 1e-12)
      throw ValueError("perspective transforms cannot define an affine solid");
  }
  Mat3 affine{};
  for (std::size_t i = 0; i < 3; ++i)
    for (std::size_t j = 0; j < 3; ++j)
      affine[i][j] = values[i][j];
  if (std::abs(determinant(affine)) < 1e-14)
    throw ValueError("matrix must be nonsingular");

  const Mat3 basis = current_basis();
  const Vec3 origin = features_detail::place_point({0, 0, 0});
  const Mat3 linear = multiply(multiply(basis, affine), transposed(basis));
  const Vec3 offset = apply(basis, {values[0][3], values[1][3], values[2][3]});
  const TopoDS_Shape transformed = general_transform(solid.wrapped(), linear, origin + offset - apply(linear, origin),
                                                     "kernel could not transform the solid");
  rec.input(solid, "body");
  return finish_solid(solid, transformed, std::move(rec).take());
}

}  // namespace scad
