"""Incremental preview: the kernel posts the parts the server lacks, the server gives each page the parts it lacks."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.editor.preview_parts import PartStore, parse_preview
from simplecadapi.runtime import live
from simplecadapi.scene import preview as P


def scene_of(*bodies, ids=None) -> P.PreviewScene:
    assembly = scad.make_assembly_rassembly("asm")
    for index, body in enumerate(bodies):
        part = scad.make_part_rpart(part_id=f"p{index}", body=body, name=f"p{index}")
        assembly = scad.add_component_rassembly(
            assembly, part, component_id=f"c{index}", placement=scad.identity_placement_rplacement()
        )
    return P.compile_preview(assembly)


def decode_frame(frame: bytes) -> tuple[dict, bytes]:
    size = int.from_bytes(frame[:4], "big")
    return json.loads(frame[4 : 4 + size]), frame[4 + size :]


class PartStoreTest(unittest.TestCase):
    def test_a_full_preview_round_trips_byte_for_byte(self) -> None:
        scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        full = P.encode_preview(scene)
        parsed = parse_preview(full)
        store = PartStore()
        store.put(parsed.parts)
        self.assertEqual(store.assemble(parsed.nodes), full)

    def test_a_delta_names_every_part_but_carries_only_the_new_ones(self) -> None:
        scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        keys = list(scene.parts)
        delta = P.encode_preview(scene, omit={keys[0]})
        parsed = parse_preview(delta)
        self.assertEqual(set(parsed.parts), {keys[1]})
        self.assertEqual(parsed.needed, set(keys))

    def test_assemble_leaves_out_what_the_reader_has(self) -> None:
        scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        parsed = parse_preview(P.encode_preview(scene))
        store = PartStore()
        store.put(parsed.parts)
        key = parsed.nodes[0]["part"]
        delta = parse_preview(store.assemble(parsed.nodes, omit={key}))
        self.assertNotIn(key, delta.parts)
        self.assertEqual(delta.needed, parsed.needed)

    def test_the_least_recently_used_part_goes_first_and_the_latest_scene_never(self) -> None:
        store = PartStore(max_bytes=1)
        a, b = (scene_of(scad.make_box_rsolid(w, 5, 5)) for w in (10, 20))
        pa, pb = parse_preview(P.encode_preview(a)), parse_preview(P.encode_preview(b))
        store.put(pa.parts, keep=pa.needed)
        store.put(pb.parts, keep=pb.needed)
        self.assertEqual(store.missing(pa.parts), set(pa.parts))  # evicted
        self.assertEqual(store.missing(pb.parts), set())  # protected: the latest scene


class KernelPostsOnlyNewPartsTest(unittest.TestCase):
    def setUp(self) -> None:
        live._posted = set()
        self.posts: list[tuple[bytes, bool]] = []
        self.scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        self.refuse = False
        original = (live._live_scene, live._post)

        def post(url, data, step, delta, timeout):
            self.posts.append((data, delta))
            if delta and self.refuse:
                raise urllib.error.HTTPError(url, 409, "missing", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]

        live._live_scene = lambda: self.scene  # type: ignore[assignment]
        live._post = post  # type: ignore[assignment]
        self.addCleanup(lambda: (setattr(live, "_live_scene", original[0]), setattr(live, "_post", original[1])))

    def parts_of(self, data: bytes) -> set[str]:
        return set(parse_preview(data).parts)

    def test_the_first_post_is_whole_and_the_same_model_again_carries_no_part(self) -> None:
        live.publish_preview("http://x/p")
        live.publish_preview("http://x/p")
        (first, first_delta), (second, second_delta) = self.posts
        self.assertFalse(first_delta)
        self.assertEqual(self.parts_of(first), set(self.scene.parts))
        self.assertTrue(second_delta)
        self.assertEqual(self.parts_of(second), set())
        self.assertEqual(parse_preview(second).needed, set(self.scene.parts))

    def test_a_changed_part_is_the_only_one_posted(self) -> None:
        live.publish_preview("http://x/p")
        before = set(self.scene.parts)
        self.scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(5, 12))
        live.publish_preview("http://x/p")
        posted = self.parts_of(self.posts[-1][0])
        self.assertEqual(len(posted), 1)
        self.assertTrue(posted.isdisjoint(before))

    def test_a_server_that_lacks_parts_is_sent_everything(self) -> None:
        live.publish_preview("http://x/p")
        self.refuse = True
        live.publish_preview("http://x/p")
        self.assertEqual([delta for _, delta in self.posts], [False, True, False])
        self.assertEqual(self.parts_of(self.posts[-1][0]), set(self.scene.parts))

    def test_a_failed_post_forgets_what_the_server_holds(self) -> None:
        live.publish_preview("http://x/p")

        def broken(*args, **kwargs):
            raise urllib.error.URLError("down")

        live._post = broken  # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            live.publish_preview("http://x/p")
        self.assertEqual(live._posted, set())


class ServerSendsPagesWhatTheyLackTest(unittest.TestCase):
    def state(self):
        pytest.importorskip("starlette")
        from simplecadapi.editor.server import WorkspaceState

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return WorkspaceState(Path(tmp.name).resolve())

    def test_a_delta_with_a_part_the_server_lacks_is_refused_with_the_keys(self) -> None:
        state = self.state()
        scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        with self.assertRaises(KeyError) as raised:
            state.set_preview(P.encode_preview(scene, omit=set(scene.parts)))
        self.assertEqual(set(raised.exception.args[0]), set(scene.parts))

    def test_the_model_the_server_holds_is_always_whole(self) -> None:
        state = self.state()
        scene = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        full = P.encode_preview(scene)
        self.assertFalse(state.set_preview(full))
        self.assertTrue(state.set_preview(P.encode_preview(scene, omit=set(scene.parts))))  # same model, parts left out
        self.assertEqual(state.latest_preview_bytes, full)

    def test_a_connected_page_is_sent_only_new_parts_and_a_late_page_everything(self) -> None:
        from starlette.testclient import TestClient

        from simplecadapi.editor.server import create_app

        state = self.state()
        first = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(4, 12))
        state.set_preview(P.encode_preview(first))
        state.latest["preview"] = {"type": "preview", "revision": 1, "unchanged": False}
        client = TestClient(create_app(state))
        with client.websocket_connect("/ws") as page, client.websocket_connect("/ws") as other:
            for socket in (page, other):
                self.assertEqual(socket.receive_json()["type"], "hello")
                header, model = decode_frame(socket.receive_bytes())
                self.assertEqual(set(parse_preview(model).parts), set(first.parts))
            # the model changes: one part is new
            second = scene_of(scad.make_box_rsolid(10, 10, 10), scad.make_cylinder_rsolid(5, 12))
            state.hub.attach_loop = None  # (the hub's loop is the app's; the test drives the send directly)
            changed = set(second.parts) - set(first.parts)
            self.assertEqual(len(changed), 1)
            state.set_preview(P.encode_preview(second, omit=set(first.parts) & set(second.parts)))
            frame = state.part_store.assemble(state.scene_nodes, omit=set(first.parts))
            self.assertEqual(set(parse_preview(frame).parts), changed)
            self.assertEqual(parse_preview(frame).needed, set(second.parts))
            # a page that asks to resync gets the whole model
            page.send_json({"type": "preview.resync"})
            _, whole = decode_frame(page.receive_bytes())
            self.assertEqual(set(parse_preview(whole).parts), set(second.parts))


if __name__ == "__main__":
    unittest.main()


class HubSendsEachPageItsOwnFrameTest(unittest.TestCase):
    def test_each_page_is_given_a_frame_made_for_the_parts_it_holds(self) -> None:
        import asyncio
        import threading
        import time

        pytest.importorskip("starlette")
        from simplecadapi.editor.ws import WsHub

        class Page:
            def __init__(self) -> None:
                self.sent: list[bytes] = []

            async def accept(self) -> None:
                pass

            async def send_bytes(self, data: bytes) -> None:
                self.sent.append(data)

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (loop.call_soon_threadsafe(loop.stop), thread.join(5)))
        hub = WsHub()
        hub.attach_loop(loop)
        old, new = Page(), Page()
        for page in (old, new):
            asyncio.run_coroutine_threadsafe(hub.connect(page), loop).result(5)  # type: ignore[arg-type]
        hub.set_known(old, {"a", "b"})  # type: ignore[arg-type]
        hub.broadcast_preview(lambda known: ",".join(sorted(known)).encode(), {"b", "c"})
        deadline = time.monotonic() + 5
        while not (old.sent and new.sent) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(old.sent, [b"a,b"])  # made from what that page holds
        self.assertEqual(new.sent, [b""])
        hub.broadcast_preview(lambda known: ",".join(sorted(known)).encode(), {"b", "c"})
        deadline = time.monotonic() + 5
        while not (len(old.sent) == 2 and len(new.sent) == 2) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(old.sent[1], b"b,c")  # and it now holds the scene it was sent
        self.assertEqual(new.sent[1], b"b,c")
