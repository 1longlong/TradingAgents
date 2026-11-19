"""Strict-offline harness for NFR-OFF-001 (counts forbidden socket attempts).

Run from the repository root::

    .venv/bin/python scripts/validate/strict_offline_harness.py

This harness runs the default, non-integration pytest suite with outbound
networking disabled by replacing the socket connection entry points with a
function that *records each attempt* and then raises ``OSError``. It then asserts
the recorded attempt count is exactly zero (``NFR-OFF-001``: zero outbound
network connection attempts during the socket-disabled non-integration run).

Scope (honest, fail-closed):
- This proves the non-integration run makes **no** outbound connection attempt
  (the count is asserted to be 0), *if* that holds. It does **NOT** assert the run
  is green: a genuine regression must still fail and is recorded separately. As of
  the 2026-11-11 repair the observed count is **0** (the former
  `test_no_data_handling` vendor-reachability probe is now mocked), so the
  zero-attempt guarantee holds on the local strict-offline run; the remote CI
  jobs are not re-run by this harness and remain a separate evidence axis
  (DEBT-034). Historically one intercepted attempt was observed there and that
  history is retained in the logbook. This is not a remote-green claim; see
  logbook 078 for the count.
- Exit code: the harness fails closed (non-zero) when a forbidden attempt is
  observed, AND it also propagates pytest's own non-zero result, so a red suite is
  never hidden. A network-attempt violation is checked and reported first; the
  pytest result is returned otherwise (a failing suite is still a non-zero exit).
- It never waives failures and is not wired into CI; it is a documented,
  reproducible local command, not a CI gate.

The attempt counter is also imported and exercised by the governance tests so the
counting/assertion logic is verified offline without spawning a subprocess.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

_FORBIDDEN_MESSAGE = "Network disabled for offline verification"


@dataclass
class SocketAttemptRecorder:
    """Records forbidden socket-connection attempts instead of connecting."""

    attempts: list[str] = field(default_factory=list)

    def __call__(self, *args: object, **kwargs: object) -> object:
        # Record the attempt (no secret/peer data; only that it happened) and
        # fail closed so no real connection is ever made.
        self.attempts.append("socket-connect-attempt")
        raise OSError(_FORBIDDEN_MESSAGE)

    @property
    def count(self) -> int:
        return len(self.attempts)

    def assert_no_attempts(self) -> None:
        if self.attempts:
            raise AssertionError(
                f"{self.count} forbidden network connection attempt(s) observed"
            )


def install_deny(recorder: SocketAttemptRecorder) -> None:
    """Replace socket connection entry points with the recording denier."""
    import socket

    socket.socket.connect = recorder  # type: ignore[method-assign]
    socket.socket.connect_ex = recorder  # type: ignore[method-assign]
    socket.create_connection = recorder  # type: ignore[assignment]


def run(argv: list[str] | None = None) -> int:
    """Run pytest under the recording denier; return a process-style exit code."""
    recorder = SocketAttemptRecorder()
    install_deny(recorder)
    import pytest

    args = argv if argv is not None else [
        "-q",
        "-p",
        "no:cacheprovider",
        "-m",
        "not integration",
    ]
    pytest_exit = pytest.main(args)
    # Fail closed on a forbidden network attempt regardless of test outcomes.
    try:
        recorder.assert_no_attempts()
    except AssertionError as exc:
        print(f"NFR-OFF-001 VIOLATION: {exc}")
        return 1
    print(f"NFR-OFF-001 OK: {recorder.count} forbidden socket attempt(s)")
    # Propagate pytest's result separately; a red suite is NOT hidden here, it is
    # reported by pytest itself (this harness only adds the attempt assertion).
    return int(pytest_exit)


if __name__ == "__main__":
    sys.exit(run())
