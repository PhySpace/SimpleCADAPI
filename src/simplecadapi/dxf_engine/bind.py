"""dxf_engine.bind — from a declared dimension to a measured one.

`bind_dim` resolves what a DimDecl measures (`of` / `between` / `extent`, or the typed forms) in its view and returns
the effective declaration the solver works on: the measured points or circle, the measuring axis, the side, and the
measured value. The number on the sheet is built here, from the measurement, never from the declared `value`:
a declared value that differs from the measurement is recorded for the checks (DIM_VALUE_MISMATCH).
"""
from __future__ import annotations

import dataclasses
import math

from . import refs
from .refs import Ref2D, RefError

DIA, TOL_OPEN, TOL_SEP, TOL_CLOSE = "⌀", "{", "|", "}"
VALUE_TOL = 0.005         # mm: a declared value this close to the measurement is the same value


def fmt_number(value, dec=None):
    """A dimension number: `dec` decimals when given, else as many as the value has, up to 2."""
    if dec is None:
        s = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        s = f"{value:.{dec}f}"
    return "0" if s in ("-0", "") else s


def split_tol(text):
    """"20{+0.021|0} H7" → ("20", "+0.021", "0", " H7"); a text without a stacked tolerance → (text, "", "", "")."""
    i = text.find(TOL_OPEN)
    j = text.find(TOL_CLOSE, i + 1)
    if i < 0 or j < 0 or TOL_SEP not in text[i:j]:
        return text, "", "", ""
    up, lo = text[i + 1:j].split(TOL_SEP, 1)
    return text[:i], up, lo, text[j + 1:]


def _dev(v):
    return "0" if abs(v) < 1e-12 else f"{v:+g}"


def dim_text(dcl, value, symbol, show_caption):
    """The text of a dimension: [N×][prefix][⌀|R]number[tolerance][ fit][ (caption)]."""
    out = (f"{dcl.count}×" if dcl.count and dcl.count > 1 else "") + (dcl.prefix or "") + symbol
    out += fmt_number(value, dcl.dec)
    if dcl.tol is not None:
        up, lo = dcl.tol
        if abs(up + lo) < 1e-12 and abs(up) > 1e-12:
            out += f"±{abs(up):g}"
        else:
            out += f"{TOL_OPEN}{_dev(up)}{TOL_SEP}{_dev(lo)}{TOL_CLOSE}"
    if dcl.fit:
        out += f" {dcl.fit}"
    if show_caption and dcl.caption:
        out += f" ({dcl.caption})"
    return out


def native_text(dcl, symbol_in_style):
    """The DXF text override of the native DIMENSION: "<>" stands for the measurement the CAD program computes itself.
    `symbol_in_style` is True for diameter/radius entities, which add their own ⌀ / R."""
    out = (f"{dcl.count}×" if dcl.count and dcl.count > 1 else "") + (dcl.prefix or "")
    if not symbol_in_style and getattr(dcl, "_sym", "") == DIA:
        out += "%%c"
    out += "<>"
    if dcl.fit:
        out += f" {dcl.fit}"
    return "" if out == "<>" else out


def _auto_side(axis, pa, pb, lbox):
    """The side of the view nearer to what is measured (ties: bottom / right)."""
    if axis == "x":
        mid = (pa[1] + pb[1]) / 2
        return "top" if mid > (lbox[1] + lbox[3]) / 2 + 1e-6 else "bottom"
    mid = (pa[0] + pb[0]) / 2
    return "left" if mid < (lbox[0] + lbox[2]) / 2 - 1e-6 else "right"


def lin_points(dcl, side):
    """The two measured points of a linear dimension for a dimension line on `side`: on a line reference the
    extension line starts at the end nearest the dimension line."""
    rr = getattr(dcl, "_refs", None)
    if rr is None:
        return dcl.p1, dcl.p2
    toward = -1.0 if side in ("bottom", "left") else 1.0
    return refs.anchor(rr[0], dcl._axis, toward), refs.anchor(rr[1], dcl._axis, toward)


def _finish_linear(dcl, ra, rb, axis, lbox, symbol=""):
    axis = refs.measuring_axis(ra, rb, axis)
    a, b = refs.position(ra, axis), refs.position(rb, axis)
    measured = abs(b - a)
    if measured < 1e-9:
        raise RefError(f"linear dimension {dcl.caption}: the two references are at the same "
                       f"{axis} position ({a:g}); there is nothing to measure along {axis}")
    pa, pb = refs.anchor(ra, axis, -1.0), refs.anchor(rb, axis, -1.0)
    side = dcl.side or _auto_side(axis, pa, pb, lbox)
    if (axis == "x") != (side in ("bottom", "top")):
        raise RefError(
            f"linear dimension {dcl.caption}: a {'horizontal' if axis == 'x' else 'vertical'} measurement has its "
            f"dimension line {'below or above (side=bottom|top)' if axis == 'x' else 'left or right (side=left|right)'}"
            f" of the view, got side={side!r}")
    eff = dataclasses.replace(dcl, semantic="linear", side=side, between=None, extent=None, of=None,
                              p1=pa, p2=pb, center=None, radius=None)
    eff._refs, eff._axis, eff._sym = (ra, rb), axis, symbol
    return eff, measured


def bind_dim(dcl, view_decl, lbox):
    """(effective DimDecl, note or None). lbox is the view's bounding box in view-local model coordinates.

    The effective declaration carries `_axis` ("x"|"y"), `_refs` (line/point references, or None for typed points),
    `_sym` (the symbol before the number), `_measured` and `_bound` (True when the geometry came from the model)."""
    who = dcl.caption or dcl.name
    try:
        if dcl.semantic == "linear":
            if dcl.extent is not None:
                x0, y0, x1, y1 = lbox
                if dcl.extent == "x":
                    ra = Ref2D("line", ((x0, y0), (x0, y1)), desc="left edge of the view")
                    rb = Ref2D("line", ((x1, y0), (x1, y1)), desc="right edge of the view")
                else:
                    ra = Ref2D("line", ((x0, y0), (x1, y0)), desc="bottom edge of the view")
                    rb = Ref2D("line", ((x0, y1), (x1, y1)), desc="top edge of the view")
                eff, measured = _finish_linear(dcl, ra, rb, dcl.extent, lbox)
                bound = True
            elif dcl.between is not None:
                ra, rb = (refs.resolve_ref(r, view_decl) for r in dcl.between)
                if ra.kind == "band":
                    ra = Ref2D("line", ra.pts, desc="axis of " + ra.desc)
                if rb.kind == "band":
                    rb = Ref2D("line", rb.pts, desc="axis of " + rb.desc)
                eff, measured = _finish_linear(dcl, ra, rb, dcl.axis, lbox)
                bound = True
            else:
                dx, dy = dcl.p2[0] - dcl.p1[0], dcl.p2[1] - dcl.p1[1]
                axis = dcl.axis or ("y" if abs(dy) >= abs(dx) else "x")
                measured = abs(dy) if axis == "y" else abs(dx)
                eff = dataclasses.replace(dcl, side=dcl.side or ("right" if axis == "y" else "bottom"))
                eff._refs, eff._axis, eff._sym = None, axis, ""
                bound = False
        else:
            if dcl.of is not None:
                ref = refs.resolve_ref(dcl.of, view_decl)
                if ref.kind == "band" and dcl.semantic == "diameter":
                    la, lb = refs.silhouettes(ref)
                    eff, measured = _finish_linear(dcl, la, lb, None, lbox, symbol=DIA)
                    eff._bound, eff._measured = True, measured
                    return eff, _value_note(dcl, measured, who)
                if ref.kind != "circle":
                    raise RefError(
                        f"{dcl.semantic} dimension {who}: the reference is {ref.desc}, which this view does not show "
                        "as a circle. Reference a circular edge or a cylinder face, in a view along its axis"
                        + (" (or from the side, for a diameter)" if dcl.semantic == "diameter" else ""))
                center, radius, bound, mid = ref.pts[0], ref.radius, True, ref.mid
            else:
                center, radius, bound, mid = tuple(dcl.center), float(dcl.radius), False, None
            measured = 2.0 * radius if dcl.semantic == "diameter" else radius
            at = dcl.at if dcl.at is not None else (mid if mid is not None else 45.0)
            eff = dataclasses.replace(dcl, of=None, center=center, radius=radius, at=at)
            eff._refs, eff._axis = None, None
            eff._sym = DIA if dcl.semantic == "diameter" else "R"
    except RefError as e:
        raise RefError(f"dimension {who} in view {dcl.view!r}: {e}") from None
    eff._bound, eff._measured = bound, measured
    return eff, _value_note(dcl, measured, who)


def _value_note(dcl, measured, who):
    if dcl.value is None or abs(dcl.value - measured) <= VALUE_TOL:
        return None
    return {"element": f"dim:{who}", "view": dcl.view, "declared": float(dcl.value), "measured": measured}
