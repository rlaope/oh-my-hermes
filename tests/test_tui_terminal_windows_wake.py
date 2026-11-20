"""The gateway wake on every platform, and on real Windows pipes (`GatewayClient.wake_fd`, `wake`, `poll`).

The wake pipe holds at most one byte, so neither signalling nor draining can
wait on a full or an empty pipe, without the non-blocking mode Windows pipes
lack before Python 3.12. The real-pipe tests run only on Windows (CI
`test-windows`), where the console backend peeks at the pipe (PeekNamedPipe).
"""

from __future__ import annotations

import os
import time
import unittest

from omh.tui import terminal_windows as tw
from omh.tui.gateway import GatewayClient, GatewaySpawn


class GatewayWakeOneByteTests(unittest.TestCase):
    """The wake pipe holds at most one byte, so no signal or drain ever waits, on any platform."""

    def client(self) -> GatewayClient:
        client = GatewayClient(GatewaySpawn((), "", {}))

        def close_wake() -> None:
            for descriptor in client._wake or ():
                os.close(descriptor)

        self.addCleanup(close_wake)
        return client

    def test_many_wakes_leave_one_byte_and_poll_takes_it(self) -> None:
        client = self.client()
        descriptor = client.wake_fd()
        for _ in range(10000):  # more than a pipe buffer holds: a write per wake would block or fail
            client.wake()
        started = time.monotonic()
        self.assertEqual(client.poll(), [])
        self.assertEqual(client.poll(), [])  # the pipe is empty now, and a second drain returns at once
        self.assertLess(time.monotonic() - started, 1.0)
        client.wake()
        self.assertEqual(os.read(descriptor, 16), b"\0")


@unittest.skipUnless(os.name == "nt", "real Windows pipes and console handles")
class WindowsRealObjectTests(unittest.TestCase):
    def available(self, descriptor: int) -> int:
        import ctypes

        count = ctypes.c_uint32(0)
        self.assertTrue(tw.load_kernel32().PeekNamedPipe(tw.os_handle(descriptor), None, 0, None, count, None))
        return count.value

    def client(self) -> GatewayClient:
        client = GatewayClient(GatewaySpawn((), "", {}))

        def close_wake() -> None:
            for descriptor in client._wake or ():
                os.close(descriptor)

        self.addCleanup(close_wake)
        return client

    def test_a_signalled_wake_is_drained_without_blocking(self) -> None:
        client = self.client()
        descriptor = client.wake_fd()
        client.wake()
        client.wake()
        self.assertEqual(self.available(descriptor), 1)
        started = time.monotonic()
        self.assertEqual(client.poll(), [])
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(self.available(descriptor), 0)

    def test_a_drain_on_an_empty_pipe_returns_at_once(self) -> None:
        client = self.client()
        descriptor = client.wake_fd()
        started = time.monotonic()
        self.assertEqual(client.poll(), [])
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(self.available(descriptor), 0)


if __name__ == "__main__":
    unittest.main()
