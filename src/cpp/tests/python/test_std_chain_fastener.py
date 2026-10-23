"""simplecadapi.std.chain and simplecadapi.std.fastener against the reference SDK."""

import pytest
from std_support import compare

import simplecadapi._cpp as scad


def test_roller_chain_sprocket():
    compare("sprocket", """
        sp = std.chain.make_roller_chain_sprocket_rsolid(
            n_teeth=18, chain_pitch=19.05, roller_diameter=12.07, sprocket_thickness=11.1, bore_radius=10.2)
        result = {"shape": describe(sp, detail=False), "meta": meta(sp, "std.chain.roller_sprocket")}
    """)
    compare("sprocket_unbored", """
        sp = std.chain.make_roller_chain_sprocket_rsolid(12, 12.7, 7.92, 5.0, roller_clearance=0.1)
        result = {"shape": describe(sp, detail=False), "meta": meta(sp, "std.chain.roller_sprocket")}
    """)


def test_roller_chain_sprocket_errors():
    compare("sprocket_errors", """
        g = std.chain.make_roller_chain_sprocket_rsolid
        ok = dict(chain_pitch=19.05, roller_diameter=12.07, sprocket_thickness=11.1)
        result = [
            refuse(lambda: g(n_teeth=5, **ok)),
            refuse(lambda: g(n_teeth=18.0, **ok)),
            refuse(lambda: g(n_teeth=True, **ok)),
            refuse(lambda: g(n_teeth=18, chain_pitch=0.0, roller_diameter=12.07, sprocket_thickness=11.1)),
            refuse(lambda: g(n_teeth=18, chain_pitch=19.05, roller_diameter=19.05, sprocket_thickness=11.1)),
            refuse(lambda: g(n_teeth=18, chain_pitch=19.05, roller_diameter=12.07, sprocket_thickness=0.0)),
            refuse(lambda: g(n_teeth=18, bore_radius=60.0, **ok)),
            refuse(lambda: g(n_teeth=18, bore_radius=-1.0, **ok)),
            refuse(lambda: g(n_teeth=18, roller_clearance=-1.0, **ok)),
            refuse(lambda: g(n_teeth=18, chain_pitch=19.05, roller_diameter=3.0, sprocket_thickness=2.0, roller_clearance=20.0)),
        ]
    """)


def test_sprocket_is_recorded_as_one_strict_cut():
    compare("graph_sprocket", """
        with scad.GraphSession() as session:
            std.chain.make_roller_chain_sprocket_rsolid(18, 19.05, 12.07, 11.1, bore_radius=10.2)
        nodes = nodes_of(session)
        cuts = [n for n in nodes if n["op"] == "make_cut_rsolid"]
        result = {"cuts": len(cuts), "tool_count": cuts[0]["params"]["tool_count"],
                  "skip": cuts[0]["params"]["skip_non_intersecting"], "policy": cuts[0]["params"]["tracking_policy"],
                  "deltas": sum("topo_delta" in n for n in nodes)}
    """)


def test_bolt_head_and_drive_styles():
    compare("bolt_styles", """
        out = {}
        for head, drive in (("hex", "none"), ("square", "slot"), ("cylindrical", "hex_socket"),
                            ("button", "cross"), ("countersunk", "slot")):
            bolt = std.fastener.make_bolt_rsolid(diameter=8.0, length=24.0, head_style=head, thread_style="partial",
                                                 thread_detail="cosmetic", drive_style=drive)
            out[head] = {"shape": describe(bolt, detail=False), "meta": meta(bolt, "std.fastener.bolt")}
        result = out
    """)


def test_bolt_thread_styles_and_catalog():
    compare("bolt_thread_styles", """
        out = {}
        for key, kwargs in {
            "none": dict(diameter=8.0, length=24.0, thread_style="none"),
            "full": dict(diameter=8.0, length=24.0, thread_style="full", thread_detail="cosmetic"),
            "partial": dict(diameter=8.0, length=24.0, thread_style="partial", thread_length=15.0, thread_detail="cosmetic"),
            "m10": dict(diameter=10.0, length=40.0, thread_detail="cosmetic"),
            "explicit_pitch": dict(diameter=9.0, length=24.0, thread_pitch=1.25, thread_detail="cosmetic"),
            "auto_full": dict(diameter=4.0, length=13.0, thread_detail="cosmetic"),
            "long": dict(diameter=6.0, length=150.0, thread_detail="cosmetic"),
            "very_long": dict(diameter=6.0, length=250.0, thread_detail="cosmetic"),
            "fillet": dict(diameter=12.0, length=30.0, thread_detail="cosmetic", underhead_fillet_radius=0.0, head_width=22.0, head_height=8.0),
        }.items():
            bolt = std.fastener.make_bolt_rsolid(**kwargs)
            out[key] = {"shape": describe(bolt, detail=False), "meta": meta(bolt, "std.fastener.bolt")}
        result = out
    """)


def test_bolt_modeled_thread():
    compare("bolt_modeled_partial", """
        bolt = std.fastener.make_bolt_rsolid(diameter=8.0, length=24.0, head_style="button", thread_style="partial",
                                             thread_detail="modeled", thread_form="v", thread_pitch=1.25,
                                             thread_depth=0.65, thread_length=18.0, drive_style="cross")
        result = {"shape": describe(bolt, detail=False), "meta": meta(bolt, "std.fastener.bolt")}
    """)
    compare("bolt_modeled_full_phase", """
        with scad.GraphSession() as session:
            bolt = std.fastener.make_bolt_rsolid(diameter=6.0, length=18.0, thread_style="full", thread_detail="modeled",
                                                 thread_form="v", thread_pitch=1.0, thread_depth=0.45)
        ops = [n["op"] for n in nodes_of(session)]
        result = {"shape": describe(bolt, detail=False), "meta": meta(bolt, "std.fastener.bolt"),
                  "rotations": ops.count("make_rotate_rshape"), "helices": ops.count("make_helix_rwire") + ops.count("make_helix_redge"),
                  "sweeps": ops.count("make_sweep_rsolid"), "cuts": ops.count("make_cut_rsolid")}
    """)


def test_bolt_errors():
    compare("bolt_errors", """
        g = std.fastener.make_bolt_rsolid
        result = [
            refuse(lambda: g(diameter=0.0, length=24.0)),
            refuse(lambda: g(diameter=8.0, length=float("nan"))),
            refuse(lambda: g(diameter=8.0, length=24.0, head_style="wing")),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_style="x")),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_detail="x")),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_form="x")),
            refuse(lambda: g(diameter=8.0, length=24.0, drive_style="x")),
            refuse(lambda: g(diameter=8.0, length=24.0, head_width=7.0)),
            refuse(lambda: g(diameter=9.0, length=24.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_length=5.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_style="partial", thread_length=24.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_style="partial", thread_length=0.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_style="full", thread_length=12.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, drive_style="none", drive_size=4.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, drive_style="slot", drive_size=20.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, drive_style="slot", drive_depth=20.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, underhead_fillet_radius=5.0)),
            refuse(lambda: g(diameter=8.0, length=24.0, thread_depth=5.0)),
            refuse(lambda: g(diameter=1.0, length=24.0, thread_pitch=1.0)),
            refuse(lambda: g(diameter=8.0, length=1.0, thread_style="full", thread_detail="modeled")),
        ]
    """)


def test_nut_styles_and_holes():
    compare("nut_styles", """
        out = {}
        for style in ("hex", "square", "round", "knurled"):
            for hole in ("through", "blind"):
                kwargs = {"hole_depth": 5.0} if hole == "blind" else {}
                nut = std.fastener.make_nut_rsolid(diameter=8.0, width=13.0, height=6.5, nut_style=style, hole_style=hole,
                                                   thread_detail="cosmetic", **kwargs)
                out[style + "_" + hole] = {"shape": describe(nut, detail=False), "meta": meta(nut, "std.fastener.nut")}
        result = out
    """)


def test_nut_modeled_thread():
    compare("nut_modeled", """
        nut = std.fastener.make_nut_rsolid(diameter=8.0, width=13.0, height=6.5)
        knurled = std.fastener.make_nut_rsolid(diameter=8.0, width=13.0, height=7.0, nut_style="knurled", hole_style="blind",
                                               hole_depth=5.5, thread_detail="modeled", thread_form="trapezoidal",
                                               thread_pitch=1.25, thread_depth=0.65, knurl_count=18)
        result = {"hex": {"shape": describe(nut, detail=False), "meta": meta(nut, "std.fastener.nut")},
                  "knurled": {"shape": describe(knurled, detail=False), "meta": meta(knurled, "std.fastener.nut")}}
    """)
    compare("nut_phase", """
        with scad.GraphSession() as session:
            nut = std.fastener.make_nut_rsolid(diameter=6.0, width=10.0, height=5.0, thread_detail="modeled",
                                               thread_form="trapezoidal", thread_pitch=1.0, thread_depth=0.45)
        ops = [n["op"] for n in nodes_of(session)]
        result = {"shape": describe(nut, detail=False), "meta": meta(nut, "std.fastener.nut"),
                  "rotations": ops.count("make_rotate_rshape"), "unions": ops.count("make_union_rsolid"),
                  "sweeps": ops.count("make_sweep_rsolid")}
    """)


def test_nut_errors():
    compare("nut_errors", """
        g = std.fastener.make_nut_rsolid
        ok = dict(diameter=8.0, width=13.0, height=6.5)
        result = [
            refuse(lambda: g(diameter=8.0, width=8.2, height=6.5)),
            refuse(lambda: g(nut_style="castle", **ok)),
            refuse(lambda: g(hole_style="slotted", **ok)),
            refuse(lambda: g(hole_style="through", hole_depth=5.0, **ok)),
            refuse(lambda: g(hole_style="blind", hole_depth=6.5, **ok)),
            refuse(lambda: g(nut_style="knurled", knurl_count=6, **ok)),
            refuse(lambda: g(nut_style="knurled", knurl_count=12.0, **ok)),
            refuse(lambda: g(diameter=9.0, width=15.0, height=6.5)),
            refuse(lambda: g(thread_depth=5.0, **ok)),
            refuse(lambda: g(diameter=8.0, width=13.0, height=0.0)),
            refuse(lambda: g(diameter=8.0, width=13.0, height=1.0)),
        ]
    """)


def test_fastener_module_surface():
    names = [n for n in scad.std.fastener.__all__ if callable(getattr(scad.std.fastener, n, None))]
    assert names == ["make_bolt_rsolid", "make_nut_rsolid"]
    assert isinstance(scad.std.fastener.make_bolt_rsolid(8.0, 24.0, thread_detail="cosmetic"), scad.Solid)
