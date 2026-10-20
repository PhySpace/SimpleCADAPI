"""One process at a time in a notebook's state directory.

Workers (see ``prefetch``) may run the same notebook at once, and a run
prunes the cache directories it did not use.  The lock is between processes:
inside one, a nested run of the same notebook (a ``use`` cycle) goes on as it
always did, and is reported, not waited for.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time

from simplecadapi.runtime.config import read_notebook_config
from simplecadapi.runtime.deps import exclusive
from test_notebook_runtime import NotebookTestCase, cell, notebook_text


class TestStateLock(NotebookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.write("n.py", notebook_text(cell("x = 1", returns="x")))
        self.config = read_notebook_config(self.path)

    def test_a_nested_run_of_the_same_notebook_is_not_waited_for(self) -> None:
        with exclusive(self.config):
            with exclusive(self.config):
                pass

    def test_another_process_waits_for_the_holder(self) -> None:
        holder = textwrap.dedent(
            f"""
            import sys, time
            from simplecadapi.runtime.config import read_notebook_config
            from simplecadapi.runtime.deps import exclusive
            with exclusive(read_notebook_config({str(self.path)!r})):
                print("locked", flush=True)
                time.sleep(1.5)
            """
        )
        process = subprocess.Popen([sys.executable, "-c", holder], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            started = time.monotonic()
            with exclusive(self.config):
                waited = time.monotonic() - started
            self.assertGreater(waited, 0.8)
        finally:
            process.wait(timeout=30)
