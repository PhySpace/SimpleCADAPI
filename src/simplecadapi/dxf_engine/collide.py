"""dxf_engine.collide — the one conflict test.

The solver (to choose a position), the evaluation (to report what is wrong) and the action interface (to accept or
reject a move) all ask the same question through `conflicts`: does this text box, with these lines, clash with anything
already on the sheet? One function, so that the report can never call a sheet clean that the diagnosis calls conflicted.

What counts as a clash (sheet millimetres):
  text box   over a keep-out zone, outside the frame, over another view, over a figure line (its own view included),
             over another text, over a dimension or extension line of another element
  lines      crossing a line of another element (a shared end point or a T-junction is normal practice), lying on top
             of one, or crossing the figure lines of another view
Centre lines are not obstacles: they are interrupted where a text stands on them (render).
"""
from __future__ import annotations

import math

WEIGHT = {"text": 100.0, "keep-out zone": 100.0, "outside frame": 100.0, "view bbox": 90.0, "figure line": 80.0,
          "dimension line": 60.0, "dimension line over another": 60.0,
          "dimension line crosses another view's figure line": 60.0}


def _r(v, nd=1):
    return round(float(v), nd)


def proper_cross(a, b, c, d, eps=0.5):
    """Strict X crossing: two segments straddle each other and share no endpoint. A shared endpoint (shared measured point) / collinear (shared
    extension line) / T-junction (an extension-line end on another line) are normal GB drawing practice and do not count as conflicts."""
    if min(math.dist(a, c), math.dist(a, d), math.dist(b, c), math.dist(b, d)) < eps:
        return False

    def ori(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    o1, o2 = ori(a, b, c), ori(a, b, d)
    o3, o4 = ori(c, d, a), ori(c, d, b)
    return o1 == -o2 and o3 == -o4 and o1 != 0 and o3 != 0


def seg_hits_obb(p, q, cx, cy, w, h, rot_deg, pad=0.3):
    """Exact test: does the segment p–q pass through the rotated rectangle (grown by pad)?"""
    return seg_clip_obb(p, q, cx, cy, w, h, rot_deg, pad) is not None


def seg_clip_obb(p, q, cx, cy, w, h, rot_deg, pad=0.3):
    """The part of the segment p–q inside the rotated rectangle (grown by pad), as parameters (t0, t1) in [0, 1];
    None when it stays outside."""
    rr = math.radians(rot_deg)
    ca, sa = math.cos(rr), math.sin(rr)

    def local(pt):
        dx, dy = pt[0] - cx, pt[1] - cy
        return dx * ca + dy * sa, -dx * sa + dy * ca

    (x0, y0), (x1, y1) = local(p), local(q)
    hw, hh = w / 2 + pad, h / 2 + pad
    t0, t1 = 0.0, 1.0
    for d, lo, hi in ((x1 - x0, -hw - x0, hw - x0), (y1 - y0, -hh - y0, hh - y0)):
        if abs(d) < 1e-12:
            if lo > 0 or hi < 0:
                return None
            continue
        ta, tb = lo / d, hi / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return None
    return (t0, t1)


def collinear_overlap(s1, s2, tol=0.3, min_len=1.0):
    """Two segments on the same line that share more than min_len of it."""
    (a, b), (c, d) = s1, s2
    l1 = math.dist(a, b)
    if l1 < 1e-6 or math.dist(c, d) < 1e-6:
        return False
    ux, uy = (b[0] - a[0]) / l1, (b[1] - a[1]) / l1
    for pt in (c, d):
        if abs((pt[0] - a[0]) * -uy + (pt[1] - a[1]) * ux) > tol:
            return False
    tc = (c[0] - a[0]) * ux + (c[1] - a[1]) * uy
    td = (d[0] - a[0]) * ux + (d[1] - a[1]) * uy
    return min(max(tc, td), l1) - max(min(tc, td), 0.0) > min_len


def conflicts(plan, key, view, cx, cy, w, h, rot, segs, text=True):
    """Every clash of one element placement, as structured obstacle data.

    view is the element's own view (its box may lie over that view, but not over its figure lines); segs are the
    element's lines, the dimension line first. text=False tests the lines only."""
    out = []
    if text:
        for i, z in enumerate(plan._zones):
            if plan._obb_sat(cx, cy, w, h, rot, z.inflate(1.0)):
                out.append({"rule": "R1", "type": "keep-out zone", "id": f"zone{i}",
                            "bbox": [_r(z.x0), _r(z.y0), _r(z.x1), _r(z.y1)]})
        fr = plan.fmt.frame
        if any(not (fr[0] <= x <= fr[2] and fr[1] <= y <= fr[3]) for x, y in plan._obb_corners(cx, cy, w, h, rot)):
            out.append({"rule": "R1", "type": "outside frame", "id": "frame", "bbox": [_r(v) for v in fr]})
        for n, vw in plan.views.items():
            bb = vw["bbox"]
            if n != view:
                if plan._obb_sat(cx, cy, w, h, rot, bb.inflate(0.5)):
                    out.append({"rule": "R1", "type": "view bbox", "id": f"view:{n}",
                                "bbox": [_r(bb.x0), _r(bb.y0), _r(bb.x1), _r(bb.y1)]})
                    nh = sum(1 for sp, sq in vw["pairs"] if seg_hits_obb(sp, sq, cx, cy, w, h, rot))
                    if nh:
                        out.append({"rule": "R1", "type": "figure line", "id": f"figure:{n}", "points": nh})
            elif plan._obb_sat(cx, cy, w, h, rot, bb.inflate(0.5)):
                nh = sum(1 for sp, sq in vw["pairs"] if seg_hits_obb(sp, sq, cx, cy, w, h, rot))
                if nh:
                    out.append({"rule": "R1", "type": "figure line", "id": f"figure:{n}", "points": nh,
                                "own_view": True})
        for k2, cx2, cy2, w2, h2, r2 in plan.text_obbs:
            if k2 != key and plan._obb_obb(cx, cy, w, h, rot, cx2, cy2, w2, h2, r2):
                out.append({"rule": "R1", "type": "text", "id": k2,
                            "center": [_r(cx2), _r(cy2)], "w": _r(w2), "h": _r(h2), "rot": _r(r2)})
    for k2, sp, sq in plan.segments:
        if k2 == key:
            continue
        hit = (text and seg_hits_obb(sp, sq, cx, cy, w, h, rot, pad=0.6)) or any(
            proper_cross(s[0], s[1], sp, sq) for s in segs)
        if hit:
            out.append({"rule": "R1", "type": "dimension line", "id": k2,
                        "seg": [[_r(sp[0]), _r(sp[1])], [_r(sq[0]), _r(sq[1])]]})
        elif segs and collinear_overlap(segs[0], (sp, sq)):
            out.append({"rule": "R1", "type": "dimension line over another", "id": k2,
                        "seg": [[_r(sp[0]), _r(sp[1])], [_r(sq[0]), _r(sq[1])]]})
    for s in segs:
        for k2, cx2, cy2, w2, h2, r2 in plan.text_obbs:
            if k2 != key and seg_hits_obb(s[0], s[1], cx2, cy2, w2, h2, r2, pad=0.3):
                if not any(c["id"] == k2 and c["type"] == "text" for c in out):
                    out.append({"rule": "R1", "type": "text", "id": k2, "by": "line",
                                "center": [_r(cx2), _r(cy2)], "w": _r(w2), "h": _r(h2), "rot": _r(r2)})
        for n in plan._seg_vs_views(s, view):
            out.append({"rule": "R1", "type": "dimension line crosses another view's figure line", "id": f"figure:{n}"})
    return out


def cost(conf):
    """How bad a placement is: 0 when nothing clashes."""
    return sum(WEIGHT.get(c["type"], 50.0) for c in conf)


def corridors(plan, key, view, cx, cy, w, h, rot, maxd=60.0, step=1.0):
    """Largest conflict-free distance a text OBB can be translated along ±x/±y (text collisions only, dimension lines excluded)."""
    res = {}
    for label, dx, dy in (("+x", 1, 0), ("-x", -1, 0), ("+y", 0, 1), ("-y", 0, -1)):
        d = 0.0
        while d < maxd and not conflicts(plan, key, view, cx + dx * (d + step), cy + dy * (d + step),
                                         w, h, rot, []):
            d += step
        res[label] = _r(d)
    return res
