"""dxf_engine.leaders — leader notes: a polyline from an anchor on the view to a block of note text."""
from __future__ import annotations

import math

from .geom2d import Box, _text_width


def solve_leaders(plan):
    from .planner import Resolved
    for dcl in plan.d.leaders:
        a = plan.tx(dcl.view, dcl.anchor)
        w = max(_text_width(t, 2.2) for t in dcl.lines)
        h = len(dcl.lines) * 4.2 + 1.0
        bbv = plan.views[dcl.view]["bbox"]
        side = -1.0 if (a[0] - bbv.x0) < (bbv.x1 - a[0]) else 1.0
        cands = [dcl.off] + list(dcl.alt_offs)
        for k in range(1, 6):
            cands.append((dcl.off[0] + side * (18.0 * k),
                          dcl.off[1] - 8.0 * k))
        final = None
        adjust = []
        for ci, off in enumerate(cands):
            tx0 = a[0] + off[0]
            ty0 = a[1] + off[1]
            box = Box(tx0, ty0 - h, tx0 + w, ty0)
            # the elbow sits above the box top: a mid-box elbow of a multi-line text would cut through the second line's height band
            elb_y = ty0 + 0.8
            near_x = (box.x0 - 1.2) if dcl.dx_dir < 0 else (box.x1 + 1.2)
            path = [a, (a[0], elb_y), (near_x, elb_y)]
            why = []
            for z in plan._zones:
                if box.overlaps(z.inflate(1.0)):
                    why.append("keep-out zone")
            if any(box.overlaps(v["bbox"]) for n, v in plan.views.items()
                   if n != dcl.view):
                why.append("over another view bbox")
            for sp, sq in zip(path, path[1:]):
                vh = plan._seg_vs_views((sp, sq), dcl.view)
                if vh:
                    mid = ((sp[0] + sq[0]) / 2, (sp[1] + sq[1]) / 2)
                    if math.dist(a, mid) > 15.0:
                        why.append(f"leader crosses {'+'.join(vh)}")

            for kk, cx2, cy2, w2, h2, r2 in plan.text_obbs:
                if f"lead:{dcl.name}" != kk and plan._obb_obb(
                        tx0, ty0 - h / 2, w, h, 0.0,
                        cx2, cy2, w2, h2, r2):
                    why.append(f"text {kk}")
            for i in range(len(path) - 1):
                seg = (path[i], path[i + 1])
                for k2, cx2, cy2, w2, h2, r2 in plan.text_obbs:
                    if plan._seg_obb(seg[0], seg[1], cx2, cy2, w2, h2, r2):
                        why.append(f"leader over text {k2}")
            for i in range(len(path) - 1):
                seg = (path[i], path[i + 1])
                for k2, sp2, sq2 in plan.segments:
                    if k2 != f"lead:{dcl.name}" and \
                            plan._seg_cross(*seg, sp2, sq2):
                        why.append(f"dimension line {k2}")
            if not why:
                final = (off, box, path)
                if ci:
                    adjust.append(f"moved ×{ci}")
                    plan.adjust_count += 1
                break
        if final is None:
            off = dcl.off
            box = Box(a[0] + off[0], a[1] + off[1] - h,
                      a[0] + off[0] + w, a[1] + off[1])
            path = [a, (a[0] + dcl.dx_dir * 12.0, box.y1 + 0.8),
                    (box.x0 - 1.2 if dcl.dx_dir < 0 else box.x1 + 1.2,
                     box.y1 + 0.8)]
            adjust.append("no free slot found (warning)")
            plan.adjust_count += 1
        else:
            off, box, path = final
        plan.text_obbs.append((f"lead:{dcl.name}",
                               (box.x0 + box.x1) / 2,
                               (box.y0 + box.y1) / 2, w, h, 0.0))
        for i in range(len(path) - 1):
            plan._reg_seg(f"lead:{dcl.name}", path[i], path[i + 1])
        plan.resolved.append(Resolved(
            "leader", dcl.name or dcl.lines[0][:12], dcl.view,
            f"off={dcl.off}", f"off={tuple(round(v, 1) for v in off)}",
            adjust, {"anchor": a, "path": path, "lines": dcl.lines,
                     "text_x": box.x0, "text_y_top": box.y1}))
