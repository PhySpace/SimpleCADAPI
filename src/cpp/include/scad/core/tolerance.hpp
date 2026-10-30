// Named numeric tolerances.
//
// Every threshold in the C++ tree that decides "is this zero / equal / parallel / small enough" and
// would otherwise be a bare `1e-9` lives here, named by what it is a tolerance FOR.  The same number
// can appear under several names on purpose: two meanings that share a value today may need to
// diverge later, and a reviewer should be able to see that they are different decisions.
//
// How to choose a tolerance
//   * Reuse a constant only when the new site asks the same question (a vector length below which
//     the direction is undefined, two sketch points that coincide, ...).  Same value is not enough.
//   * Add a new constant when the question is new, even if its value equals an existing one.  Give
//     it a one-line comment that says what it is a tolerance for and, when the site ports old
//     Python, the SimpleCADAPI module the number comes from.
//   * Leave algorithm-local numbers (sample counts, scale factors, iteration limits, a solver's own
//     pivoting thresholds) where they are, next to the code that explains them.
//   * OCCT's own tolerances (`Precision::Confusion()` and friends) are not copied here: write them
//     where the call into OCCT happens.
//   * Changing a value here changes behaviour everywhere it is used, and several of these are
//     defaults visible in the Python signatures (`help(...)`) and in the goldens.  Run the tests.
//
// Table of meanings (value, group)
//   kDegenerateNorm            1e-12  vector / bounds diagonal with no usable direction or extent
//   kZeroDirectionNorm         1e-15  direction vector that is exactly zero for practical purposes
//   kUndefinedNormal           1e-14  plane / surface normal or extrusion direction that is undefined
//   kSingularDeterminant       1e-14  3x3 matrix determinant of a non-invertible transform
//   kAffineBottomRow           1e-12  4x4 matrix bottom row must be (0, 0, 0, 1) within this
//   kMirrorNormalNorm          1e-10  mirror plane normal of zero length
//   kParallelCrossNorm         1e-10  |x cross n| below this: x_dir is parallel to the normal
//   kParallelCosineGap         1e-12  1 - |cos| below this: two axes are parallel
//   kNegligibleLength          1e-9   model-space vector / axis length treated as zero
//   kCoincidentPoints          1e-9   two points (sketch plane, section centroids) coincide
//   kEmptyVolume               1e-12  a solid / overlap volume below this is empty
//   kCatalogDiameter           1e-9   a diameter equals a catalog nominal (math.isclose abs_tol)
//   kArcSweepZero              1e-12  arc sweep (radians) below this is zero
//   kArcRadiusRelative         1e-7   arc endpoints may differ in radius by this fraction
//   kBaseCircleClearance       1e-8   root / tip circle compared with the involute base circle
//   kCutterOverrunFloor        1e-5   floor of the overshoot that makes a cutter pass through a face
//   kCutterOverrunRelative     1e-4   the same overshoot as a fraction of the feature size
//   kVolumeIntegration         1e-9   Gauss-Kronrod error target for exact volume / centroid
//   kVolumeEstimate            1e-5   Gauss-Kronrod error target for the quick volume estimate
//   kFuzzyUnionRelative        1e-7   fuzzy value of a union as a fraction of the operands' span
//   kFuzzyUnionMin / Max       1e-7 / 1e-5   clamp of that fuzzy value (model units); Min is also
//                                      the default fuzzy value of tracked_union
//   kSurfaceCoincidentDistance 1e-6   two analytic surfaces coincide: offset of planes / axes / centres
//   kSurfaceRadiusMatch        1e-7   two analytic surfaces coincide: radii agree
//   kParallelAxisCosine        0.999  two analytic surfaces coincide: |cos| of axis angle at least this
//   kSketchSolveResidual       1e-7   default residual target of the sketch constraint solver
//   kSurfaceTrim               1e-7   default tolerance of a carrier surface / trimmed face
//   kFitError                  1e-3   default maximum error of a fitted B-spline / network surface
//   kSewing                    1e-6   default tolerance for sewing faces / joining free boundaries
//   kSplineInterpolation       1e-6   default tolerance of an interpolating spline
//   kOffsetTolerance           1e-4   default tolerance of a solid offset
//   kFillingTolerance2d / 3d   1e-5 / 1e-4   default tolerances of the surface filling algorithm
//   kDuplicateParameter        1e-12  consecutive knots / samples closer than this are the same
//   kInteriorKnotSpacing       1e-9   spacing threshold for interior knots of a fitted B-spline
#pragma once

namespace scad::tol {

inline constexpr double kDegenerateNorm = 1e-12;     // vector length / bounds diagonal that has no direction or extent
inline constexpr double kZeroDirectionNorm = 1e-15;  // direction vector that is zero for practical purposes
inline constexpr double kUndefinedNormal = 1e-14;    // plane/surface normal or direction magnitude: undefined below
inline constexpr double kSingularDeterminant = 1e-14;   // |det| of a 3x3 transform basis: non-invertible below
inline constexpr double kAffineBottomRow = 1e-12;       // 4x4 matrix bottom row must equal (0, 0, 0, 1) within this
inline constexpr double kMirrorNormalNorm = 1e-10;      // mirror plane normal length treated as zero
inline constexpr double kParallelCrossNorm = 1e-10;     // |x cross normal| below this: x_dir parallel to normal
inline constexpr double kParallelCosineGap = 1e-12;     // 1 - |cos| below this: two axes are parallel
inline constexpr double kNegligibleLength = 1e-9;       // model-space vector / axis length treated as zero
inline constexpr double kCoincidentPoints = 1e-9;       // two points coincide
inline constexpr double kEmptyVolume = 1e-12;           // solid / overlap volume below this is empty
inline constexpr double kCatalogDiameter = 1e-9;        // a diameter equals a catalog nominal (abs_tol)
inline constexpr double kArcSweepZero = 1e-12;          // arc sweep in radians below this is zero
inline constexpr double kArcRadiusRelative = 1.0e-7;    // arc endpoint radius mismatch, fraction of the radius
inline constexpr double kBaseCircleClearance = 1e-8;    // root / tip circle against the involute base circle
inline constexpr double kCutterOverrunFloor = 1e-5;     // minimum cutter overshoot past a face
inline constexpr double kCutterOverrunRelative = 1e-4;  // cutter overshoot as a fraction of the feature size
inline constexpr double kVolumeIntegration = 1e-9;      // Gauss-Kronrod error target, exact volume / centroid
inline constexpr double kVolumeEstimate = 1e-5;         // Gauss-Kronrod error target, quick volume estimate
inline constexpr double kFuzzyUnionRelative = 1e-7;     // fuzzy value of a union, fraction of the operands' span
inline constexpr double kFuzzyUnionMin = 1e-7;          // lower clamp of that fuzzy value (also tracked_union default)
inline constexpr double kFuzzyUnionMax = 1e-5;          // upper clamp of that fuzzy value
inline constexpr double kSurfaceCoincidentDistance = 1e-6;  // analytic surfaces coincide: plane/axis/centre offset
inline constexpr double kSurfaceRadiusMatch = 1e-7;         // analytic surfaces coincide: radii agree
inline constexpr double kParallelAxisCosine = 0.999;        // analytic surfaces coincide: min |cos| between axes
inline constexpr double kSketchSolveResidual = 1e-7;        // default residual target of the sketch solver
inline constexpr double kSurfaceTrim = 1e-7;                // default tolerance of a carrier surface / trimmed face
inline constexpr double kFitError = 1e-3;                   // default maximum error of a fitted curve / surface
inline constexpr double kSewing = 1e-6;                     // default sewing / free-boundary joining tolerance
inline constexpr double kSplineInterpolation = 1e-6;        // default tolerance of an interpolating spline
inline constexpr double kOffsetTolerance = 1e-4;            // default tolerance of a solid offset
inline constexpr double kFillingTolerance2d = 1e-5;         // default 2D tolerance of the surface filling algorithm
inline constexpr double kFillingTolerance3d = 1e-4;         // default 3D tolerance of the surface filling algorithm
inline constexpr double kDuplicateParameter = 1e-12;        // consecutive knots / samples closer than this are the same
inline constexpr double kInteriorKnotSpacing = 1e-9;        // minimum spacing of interior knots of a fitted B-spline

}  // namespace scad::tol
