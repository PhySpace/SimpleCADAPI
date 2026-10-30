"""The editor's post-run latency: vectorised edge keys, preview prewarm, one kernel round trip per settle."""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
import tempfile

import numpy as np
import pytest

import simplecadapi as scad
from simplecadapi.editor.kernel import MarimoKernel
from simplecadapi.scene import prewarm, preview
from simplecadapi.scene.render_mesh import _position_key, _position_keys, cad_to_gltf


class PositionKeysTest(unittest.TestCase):
    """``_position_keys`` is ``_position_key(cad_to_gltf(point))`` for each point: same bytes, one numpy pass."""

    def test_matches_the_scalar_path_byte_for_byte(self) -> None:
        rng = np.random.default_rng(7)
        points = [tuple(row) for row in rng.uniform(-5000, 5000, size=(500, 3))]
        points += [(0.0, -0.0, 1e-46), (-0.0, 0.0, -1e-46), (123456.789, -98765.4321, 3.3e5), (1e12, -1e12, 0.0), (1e-3, 1e-3, 1e-3)]
        self.assertEqual(_position_keys(points), [_position_key(cad_to_gltf(point)) for point in points])

    def test_an_empty_polyline_has_no_keys(self) -> None:
        self.assertEqual(_position_keys([]), [])

    def test_the_profile_errors_are_unchanged(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            _position_keys([(float("nan"), 0.0, 0.0)])
        with self.assertRaisesRegex(ValueError, "overflowed"):
            _position_keys([(1e300, 0.0, 0.0)])


class PrewarmTest(unittest.TestCase):
    def setUp(self) -> None:
        preview.clear_preview_cache()

    def test_solids_of_finds_parts_assemblies_and_solids_once(self) -> None:
        box = scad.make_box_rsolid(10, 10, 10)
        part = scad.make_part_rpart(part_id="p", body=box, name="p")
        self.assertEqual([s.topo_id for s in prewarm.solids_of([part, part, box])], [box.topo_id, box.topo_id])
        self.assertEqual(list(prewarm.solids_of([1, "x", None, {"a": box}])), [])

    def test_a_submitted_solid_is_in_the_preview_cache_afterwards(self) -> None:
        box = scad.make_box_rsolid(12, 8, 5)
        key = preview.part_key(box, preview.DEFAULT_LINEAR_TOLERANCE, preview.DEFAULT_ANGULAR_TOLERANCE)
        self.assertIsNone(preview._recall(key))
        self.assertEqual(prewarm.submit([box]), 1)
        deadline = time.monotonic() + 10
        while preview._recall(key) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(preview._recall(key))

    def test_nothing_a_cell_defined_can_make_submit_fail(self) -> None:
        class Hostile:
            def __iter__(self):
                raise RuntimeError("boom")

        self.assertEqual(prewarm.submit(Hostile()), 0)

    def test_meshing_beside_other_work_gives_the_same_mesh(self) -> None:
        """``cached_mesh`` runs without the interpreter lock: a mesh made on another thread is the one made here."""

        solid = scad.make_cylinder_rsolid(6, 20)
        made: list = []
        worker = threading.Thread(target=lambda: made.append(preview.preview_solid(solid)))
        worker.start()
        for _ in range(20):
            scad.make_box_rsolid(5, 5, 5)  # the main thread keeps computing meanwhile
        worker.join(10)
        self.assertEqual(len(made), 1)
        again = preview.preview_solid(solid)
        self.assertIs(made[0], again)  # served from the cache, not meshed twice


class OneRoundTripTest(unittest.TestCase):
    """A settle lists the cells in the call that publishes the preview; nothing else reuses that listing."""

    def kernel(self) -> tuple[MarimoKernel, list[str]]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "n.py"
        path.write_text("x = 1\n")
        calls: list[str] = []
        kernel = MarimoKernel(path, server_port=8123)

        def run(code: str, timeout) -> dict:  # the HTTP call under MarimoKernel.execute, which is the real one
            calls.append("preview" if "SCA-PREVIEWED" in code else "cells")
            log = '[{"id": "a", "name": "_", "code": "x = 1", "status": "idle"}]\nSCA-PREVIEWED 1 1 10\n'
            return {"log": log}

        kernel._execute = run  # type: ignore[method-assign]
        return kernel, calls

    def test_publishing_lists_the_cells_in_the_same_call(self) -> None:
        kernel, calls = self.kernel()
        result = kernel.publish_preview("http://x/preview", step="n")
        self.assertEqual(result, {"ok": True, "nodes": 1, "parts": 1, "bytes": 10})
        self.assertEqual([c["id"] for c in kernel.list_cells()], ["a"])
        self.assertEqual(calls, ["preview"])  # one call into the kernel, not two

    def test_the_listing_is_used_once(self) -> None:
        kernel, calls = self.kernel()
        kernel.publish_preview("http://x/preview")
        kernel.list_cells()
        kernel.list_cells()
        self.assertEqual(calls, ["preview", "cells"])

    def test_a_listing_older_than_the_call_that_followed_is_not_reused(self) -> None:
        kernel, calls = self.kernel()
        kernel.publish_preview("http://x/preview")
        kernel.execute("anything")  # something ran in the kernel meanwhile
        kernel.list_cells()
        self.assertEqual(calls, ["preview", "cells", "cells"])


if __name__ == "__main__":
    unittest.main()


class PreviewPushTest(unittest.TestCase):
    """The model reaches a page with the event that announces it: one binary frame, no second request."""

    PREVIEW = b"SCAPREV1" + b"\x00" * 64

    def state(self):
        pytest.importorskip("starlette")
        from simplecadapi.editor.server import WorkspaceState

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = WorkspaceState(Path(tmp.name).resolve())
        self.text: list[dict] = []
        self.binary: list[bytes] = []
        state.hub.broadcast = self.text.append  # type: ignore[method-assign]
        state.hub.broadcast_bytes = self.binary.append  # type: ignore[method-assign]
        return state

    @staticmethod
    def decode(frame: bytes) -> tuple[dict, bytes]:
        import json

        size = int.from_bytes(frame[:4], "big")
        return json.loads(frame[4 : 4 + size].decode("utf-8")), frame[4 + size :]

    def test_the_frame_is_envelope_then_model(self) -> None:
        from simplecadapi.editor.ws import preview_frame

        envelope = {"type": "preview", "revision": 3, "name": "näme", "size": 72}
        header, model = self.decode(preview_frame(envelope, self.PREVIEW))
        self.assertEqual(header, envelope)
        self.assertEqual(model, self.PREVIEW)

    def test_a_new_model_is_pushed_as_one_binary_frame(self) -> None:
        state = self.state()
        state.latest_preview_bytes = self.PREVIEW
        state.emit({"type": "preview", "revision": 1, "name": "n", "size": len(self.PREVIEW), "unchanged": False})
        self.assertEqual(self.text, [])
        header, model = self.decode(self.binary[0])
        self.assertEqual((header["type"], header["revision"]), ("preview", 1))
        self.assertEqual(model, self.PREVIEW)

    def test_a_model_already_on_screen_is_only_a_notice(self) -> None:
        state = self.state()
        state.latest_preview_bytes = self.PREVIEW
        state.emit({"type": "preview", "revision": 2, "unchanged": True})
        self.assertEqual(self.binary, [])
        self.assertEqual(self.text[0]["unchanged"], True)

    def test_other_envelopes_stay_text(self) -> None:
        state = self.state()
        state.latest_preview_bytes = self.PREVIEW
        state.emit({"type": "status", "error": ""})
        self.assertEqual(self.binary, [])
        self.assertEqual(self.text, [{"type": "status", "error": ""}])

    def test_a_page_that_joins_late_is_given_the_model_itself(self) -> None:
        from starlette.testclient import TestClient

        from simplecadapi.editor.server import create_app

        state = self.state()
        state.latest_preview_bytes = self.PREVIEW
        # the envelope the last run left behind said "unchanged": a new page has nothing on screen
        state.latest["preview"] = {"type": "preview", "revision": 5, "name": "n", "size": len(self.PREVIEW), "unchanged": True}
        with TestClient(create_app(state)).websocket_connect("/ws") as socket:
            self.assertEqual(socket.receive_json()["type"], "hello")
            header, model = self.decode(socket.receive_bytes())
        self.assertEqual((header["revision"], header["unchanged"]), (5, False))
        self.assertEqual(model, self.PREVIEW)

    def test_the_http_route_still_serves_the_latest_model(self) -> None:
        from starlette.testclient import TestClient

        from simplecadapi.editor.server import create_app

        state = self.state()
        state.latest_preview_bytes = self.PREVIEW
        self.assertEqual(TestClient(create_app(state)).get("/api/preview/latest").content, self.PREVIEW)


class RepeatedParamTest(unittest.TestCase):
    """A value the model already has is not a rebuild (a drag that pauses sends its value again on release)."""

    def state(self):
        pytest.importorskip("starlette")
        from simplecadapi.editor.server import WorkspaceState
        from simplecadapi.editor.templates import create_notebook
        from simplecadapi.runtime.params import ParamSpec

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        state = WorkspaceState(root, create_notebook(root, "bracket", "part"))
        state.specs = {"RADIUS": ParamSpec("RADIUS", "", "c1", 1, "float", "literal", 10.0, "slider", 1.0, 50.0, 1.0)}
        self.runs: list[list[str]] = []
        state.emit_params = lambda: None  # type: ignore[method-assign]
        state.schedule_settle = lambda: None  # type: ignore[method-assign]
        runs = self.runs
        state.kernel = type("K", (), {"run_until_settled": lambda self, cells: runs.append(list(cells))})()  # type: ignore[assignment]
        return state

    def test_the_same_value_twice_rebuilds_once(self) -> None:
        state = self.state()
        state._apply_params(state.kernel, {"RADIUS": 40.0})
        state._apply_params(state.kernel, {"RADIUS": 40.0})
        self.assertEqual(self.runs, [["c1"]])

    def test_a_different_value_and_a_return_to_the_source_value_each_rebuild(self) -> None:
        state = self.state()
        for value in (40.0, 25.0, 10.0):
            state._apply_params(state.kernel, {"RADIUS": value})
        self.assertEqual(len(self.runs), 3)

    def test_the_source_value_when_nothing_is_saved_is_not_a_rebuild(self) -> None:
        state = self.state()
        state._apply_params(state.kernel, {"RADIUS": 10.0})
        self.assertEqual(self.runs, [])

    def test_after_a_failed_run_the_same_value_is_a_retry(self) -> None:
        state = self.state()
        state._apply_params(state.kernel, {"RADIUS": 40.0})
        state._last_publish_error = "the cell failed"
        state._apply_params(state.kernel, {"RADIUS": 40.0})
        self.assertEqual(len(self.runs), 2)


class SignatureBesideTheBuildTest(unittest.TestCase):
    """The signature of a publish is taken beside the build and files that publish's model, whatever came after."""

    def state(self):
        pytest.importorskip("starlette")
        from simplecadapi.editor.server import WorkspaceState
        from simplecadapi.editor.templates import create_notebook

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        state = WorkspaceState(root, create_notebook(root, "bracket", "part"))
        self.filed: list[tuple[str, bytes]] = []
        state.remember_model = lambda notebook, signature, data: self.filed.append((signature, data))  # type: ignore[method-assign]
        state.write_snapshot = lambda: None  # type: ignore[method-assign]
        return state

    def test_the_signature_is_taken_in_the_background_and_waited_for_when_filing(self) -> None:
        import threading

        state = self.state()
        release = threading.Event()

        def slow(notebook):
            release.wait(5)
            return "sig-1"

        state._signature = slow  # type: ignore[method-assign]
        state._sign_in_background()
        self.assertIsNone(state._publish_signature)  # not there yet: nothing waited for it
        signing = state._signing
        worker = threading.Thread(target=state.after_publish, args=(0.0, 10, signing, b"model-1"))
        worker.start()
        self.assertEqual(self.filed, [])  # filing waits for the signature
        release.set()
        worker.join(5)
        self.assertEqual(self.filed, [("sig-1", b"model-1")])

    def test_a_later_publish_does_not_change_the_pair_of_an_earlier_one(self) -> None:
        state = self.state()
        signatures = iter(["sig-1", "sig-2"])
        state._signature = lambda notebook: next(signatures)  # type: ignore[method-assign]
        state._sign_in_background()
        first = state._signing
        state._sign_in_background()  # the next publish starts before the first one is filed
        state.after_publish(0.0, 1, first, b"model-1")
        self.assertEqual(self.filed, [("sig-1", b"model-1")])

    def test_a_failed_signature_files_nothing(self) -> None:
        state = self.state()

        def broken(notebook):
            raise OSError("gone")

        state._signature = broken  # type: ignore[method-assign]
        state._sign_in_background()
        state.after_publish(0.0, 1, state._signing, b"model")
        self.assertEqual(self.filed, [])


class StoredModelTest(unittest.TestCase):
    """A model kept on disk is whole; a damaged or partial file is no reason for the editor not to start."""

    def state(self):
        pytest.importorskip("starlette")
        from simplecadapi.editor.server import WorkspaceState
        from simplecadapi.editor.templates import create_notebook

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.path = create_notebook(root, "bracket", "part")
        return WorkspaceState(root, self.path)

    def scene(self):
        assembly = scad.make_assembly_rassembly("a")
        for index, body in enumerate((scad.make_box_rsolid(5, 5, 5), scad.make_cylinder_rsolid(3, 6))):
            part = scad.make_part_rpart(part_id=f"p{index}", body=body, name=f"p{index}")
            assembly = scad.add_component_rassembly(assembly, part, component_id=f"c{index}", placement=scad.identity_placement_rplacement())
        return preview.compile_preview(assembly)

    def test_a_preview_that_leaves_parts_out_is_not_kept(self) -> None:
        state = self.state()
        scene = self.scene()
        state.remember_model(self.path, "sig", preview.encode_preview(scene, omit=set(scene.parts)))
        self.assertIsNone(state._recall_model(self.path, "sig"))

    def test_a_whole_preview_and_opaque_bytes_are_kept(self) -> None:
        state = self.state()
        state.remember_model(self.path, "sig", preview.encode_preview(self.scene()))
        self.assertIsNotNone(state._recall_model(self.path, "sig"))
        state.remember_model(self.path, "sig2", b"PKG")
        self.assertEqual(state._recall_model(self.path, "sig2"), b"PKG")

    def test_restoring_a_partial_file_leaves_the_editor_able_to_start(self) -> None:
        state = self.state()
        scene = self.scene()
        delta = preview.encode_preview(scene, omit=set(scene.parts))
        state._packages["bracket.py"] = (state._signature(self.path), delta)  # what an older build could have left
        self.assertFalse(state._restore(self.path))
