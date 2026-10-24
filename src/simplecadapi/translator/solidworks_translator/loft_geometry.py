"""Exact curve recipes for editable cross-kernel guided loft features."""


def canonical_guided_loft(result):
    import simplecadapi._cpp as native

    return native._guided_loft_recipe(result) if result is not None else None
