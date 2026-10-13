# Portable build123d feature traces

These fixtures contain the actual operation inputs captured from six of the
50 build123d examples supplied for the converter: lines and arcs, a selected
circular fillet, a mirrored profile, one closed font glyph with a hole, and a
nonplanar spring sweep, and a spherical cut/fillet followed by nonuniform scale.
The glyph is feature `s3` of the text example; the affine case retains the first
eight features of the keycap example. Other traces retain their entire history.

The tests require SimpleCADAPI but do not import build123d, download source
programs, load result BReps, or use paths outside the repository. Curve data
contains exact analytic geometry or B-spline poles, knots, multiplicities,
and weights; it is not a mesh or a fitted final-body snapshot.

Reference volumes use OCCT's adaptive Gauss–Kronrod integration with
`eps=1e-9` and B-spline span splitting. Original non-adaptive volumes remain
as diagnostic data because they differ materially on closed rational curves.
Each fixture records its build123d and source-kernel versions.
