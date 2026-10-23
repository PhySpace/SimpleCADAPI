from ref import close, golden


def test_golden_roundtrip_for_a_box():
    import simplecadapi._cpp as scad
    from simplecadapi._cpp import _testing

    expected = golden(
        "foundation_box_10_20_30",
        """
        import simplecadapi.ql as ql
        box = scad.make_box_rsolid(10, 20, 30)
        result = {"volume": box.get_volume(), "faces": len(ql.faces().resolve(box)),
                  "edges": len(ql.edges().resolve(box))}
        """,
    )
    box = _testing.box(10, 20, 30)
    got = {"volume": box.get_volume(), "faces": len(box.faces()), "edges": len(box.edges())}
    assert close(got, expected)
