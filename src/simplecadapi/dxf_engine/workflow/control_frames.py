"""Place and draw explicit, single-segment geometric tolerance frames."""

from __future__ import annotations

from decimal import Decimal

from ezdxf.enums import TextEntityAlignment
from simplecadapi.dxf_engine.collide import conflicts


SYMBOLS = {
    "flatness": (((-1.7, -0.8), (1.0, -0.8), (1.7, 0.8), (-1.0, 0.8), (-1.7, -0.8)),),
    "parallelism": (((-1.6, -1), (-0.3, 1)), ((0.3, -1), (1.6, 1))),
    "perpendicularity": (((0, 1.2), (0, -1.1)), ((-1.6, -1.1), (1.6, -1.1))),
    "position": (((-1.8, 0), (1.8, 0)), ((0, -1.8), (0, 1.8))),
}


def place_control_frames(plan, declarations):
    placed = []
    for row in declarations:
        value = format(Decimal(str(row["value"])).normalize(), "f")
        cells = [
            7.0,
            max(10.0, 2.5 * len(value) + (7 if row["diameter_zone"] else 3)),
        ] + [7.0] * len(row["datums"])
        width, height = sum(cells), 6.0
        anchor = plan.tx(row["view"], row["anchor"])
        dx, dy = row["offset"]
        offsets = [(dx, dy), (-dx, dy), (dx, -dy), (-dx, -dy)]
        problems = set()
        key = f"fcf:{row['name']}"
        for xoff, yoff in offsets:
            x = anchor[0] + xoff - (width if xoff < 0 else 0)
            y = anchor[1] + yoff - height / 2
            center = (x + width / 2, y + height / 2)
            knee = (anchor[0], center[1])
            join = (x + (width if xoff < 0 else 0), center[1])
            segments = [(anchor, knee), (knee, join)]
            hits = conflicts(
                plan, key, row["view"], *center, width, height, 0, segments
            )
            # The boxed control frame should stay completely outside the view it annotates.
            if plan._obb_sat(
                *center, width, height, 0, plan.views[row["view"]]["bbox"].inflate(0.5)
            ):
                problems.add(f"view:{row['view']}")
                continue
            if hits:
                problems.update(hit["id"] for hit in hits)
                continue
            plan.text_obbs.append((key, *center, width, height, 0))
            for start, end in segments:
                plan._reg_seg(key, start, end)
            placed.append(
                row
                | dict(
                    x=x,
                    y=y,
                    height=height,
                    cells=cells,
                    display_value=value,
                    leader=(anchor, knee, join),
                )
            )
            break
        else:
            raise ValueError(
                f"Feature control frame {row['name']}: adjust offset to clear {', '.join(sorted(problems))}"
            )
    return placed


def draw_control_frames(doc, frames):
    if not frames:
        return False
    layer = "FEATURE_CONTROL"
    doc.layers.new(layer, dxfattribs={"color": 7, "lineweight": 18})
    msp = doc.modelspace()
    attributes = {"layer": layer}
    for row in frames:
        x, y, height = row["x"], row["y"], row["height"]
        end = x + sum(row["cells"])
        msp.add_lwpolyline(
            [(x, y), (end, y), (end, y + height), (x, y + height)],
            close=True,
            dxfattribs=attributes,
        )
        anchor, knee, join = row["leader"]
        msp.add_lwpolyline([anchor, knee, join], dxfattribs=attributes)
        # The first segment is vertical, leaving room for a filled arrow at the witness.
        arrow_y = anchor[1] + (2 if knee[1] > anchor[1] else -2)
        msp.add_solid(
            [anchor, (anchor[0] - 0.65, arrow_y), (anchor[0] + 0.65, arrow_y)],
            dxfattribs=attributes,
        )
        middle_y = y + height / 2
        symbol_center = (x + row["cells"][0] / 2, middle_y)
        for stroke in SYMBOLS[row["characteristic"]]:
            msp.add_lwpolyline(
                [(symbol_center[0] + dx, symbol_center[1] + dy) for dx, dy in stroke],
                dxfattribs=attributes,
            )
        if row["characteristic"] == "position":
            msp.add_circle(symbol_center, 1.3, dxfattribs=attributes)

        cursor = x + row["cells"][0]
        for index, (width, text) in enumerate(
            zip(row["cells"][1:], (row["display_value"], *row["datums"]), strict=True)
        ):
            msp.add_line((cursor, y), (cursor, y + height), dxfattribs=attributes)
            middle_x = cursor + width / 2
            if index == 0 and row["diameter_zone"]:
                symbol_x = cursor + 2.5
                msp.add_circle((symbol_x, middle_y), 0.95, dxfattribs=attributes)
                msp.add_line(
                    (symbol_x - 1.3, middle_y - 1.3),
                    (symbol_x + 1.3, middle_y + 1.3),
                    dxfattribs=attributes,
                )
                middle_x += 1.8
            msp.add_text(
                text, dxfattribs=attributes | {"height": 2.5, "style": "CJK"}
            ).set_placement(
                (middle_x, middle_y), align=TextEntityAlignment.MIDDLE_CENTER
            )
            cursor += width
    return True
