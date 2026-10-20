"""Restoring a pickled shape: same tags as before, in time linear in its size.

A cell's value is stored as a pickle (the cell cache), and restoring it is the
main cost of a cached run.  The tag cache of every entity is rebuilt on the
way; it must be rebuilt once per entity, not once per entity per ancestor.
"""

from __future__ import annotations

import pickle
import unittest

import simplecadapi as scad
from simplecadapi.core import TaggedMixin, TagScope


def entities(root):
    """Every wrapper below *root* (and *root*), once."""

    seen, order, stack = set(), [], [root]
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        order.append(item)
        stack.extend(item.get_children())
    return order


def effective_tags(root):
    return {item.topo_id: frozenset(item._list_tags(TagScope.EFFECTIVE)) for item in entities(root)}


def tagged_box():
    box = scad.make_box_rsolid(
        20.0, 10.0, 5.0, tag_prefix="t.box", result_tag="part.box"
    )
    cut = scad.cut_rsolid(
        box, scad.make_cylinder_rsolid(radius=2.0, height=20.0, bottom_face_center=(10.0, 5.0, -5.0))
    )
    cut._apply_tag("inherited.down", propagate=True)
    return cut


class TestShapeRestore(unittest.TestCase):
    def test_every_entity_keeps_its_effective_tags(self) -> None:
        shape = tagged_box()
        before = effective_tags(shape)
        self.assertTrue(any("inherited.down" in tags for tags in before.values()))
        restored = pickle.loads(pickle.dumps(shape))
        self.assertEqual(effective_tags(restored), before)

    def test_the_tag_cache_is_rebuilt_a_bounded_number_of_times(self) -> None:
        shape = tagged_box()
        payload = pickle.dumps(shape)
        count = len(entities(shape))
        calls = 0
        original = TaggedMixin._refresh_tag_cache

        def counted(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return original(self, *args, **kwargs)

        TaggedMixin._refresh_tag_cache = counted
        try:
            pickle.loads(payload)
        finally:
            TaggedMixin._refresh_tag_cache = original
        self.assertLessEqual(calls, 3 * count, f"{calls} refreshes for {count} entities")


if __name__ == "__main__":
    unittest.main()


def drilled_plate():
    plate = scad.make_box_rsolid(60.0, 40.0, 6.0)
    for index in range(24):
        hole = scad.make_cylinder_rsolid(radius=1.5, height=20.0, bottom_face_center=(5.0 + index % 6 * 9, 5.0 + index // 6 * 9, -5.0))
        plate = scad.cut_rsolid(plate, hole)
    return plate


class TestShapePayload(unittest.TestCase):
    def test_the_stored_geometry_is_compressed(self) -> None:
        from simplecadapi._internal.shape_pickle import _write_shape

        shape = drilled_plate()
        raw = _write_shape(shape.wrapped)
        self.assertGreater(len(raw), 10_000)  # something to compress
        payload = shape.__reduce__()[1][1]
        self.assertLess(len(payload), len(raw) // 2)

    def test_an_entry_stored_before_compression_is_still_read(self) -> None:
        from simplecadapi._internal.shape_pickle import _write_shape, restore_shape

        shape = drilled_plate()
        before = effective_tags(shape)
        name, payload, states = shape.__reduce__()[1]
        raw = _write_shape(shape.wrapped)
        self.assertEqual(name, type(shape).__name__)
        legacy = restore_shape(name, raw, states)
        self.assertEqual(effective_tags(legacy), before)
        self.assertAlmostEqual(legacy.get_volume(), shape.get_volume(), places=6)

