"""The active retry session belongs to one execution context, not the process.

The retry budget is read by vendors through ``get_active_retry_session`` to
decide whether they are inside a routed call. That lookup used to read a
module-level list, so two threads that interleaved ``retry_session`` blocks
could each read the other's session (and exit pop whatever was on top).

The contract these tests pin:

    no active context          -> None (standalone: the vendor's own defaults)
    nested entry               -> innermost session; exit restores the outer one
    normal/exception/cancel/   -> the previous value is restored on every path
    interrupt                     and nothing is left behind afterwards
    two threads interleaved    -> each thread sees only its own session, and
                                  one thread's exit never clears the other's
    a new thread/task          -> starts with no session (never guessed/copied)
    two asyncio tasks, one loop-> isolated from each other

Thread ordering is controlled with ``Barrier``/``Event`` only: no ``sleep`` and
no reliance on how the scheduler happens to interleave.
"""
from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from tradingagents.dataflows.retry_session import (
    RetryBudget,
    RetrySession,
    get_active_retry_session,
    retry_session,
)

# A thread that never finishes would otherwise hang the suite instead of
# failing it; every ordering primitive below also carries its own timeout.
_JOIN_TIMEOUT = 10.0


def session(max_attempts: int = 2) -> RetrySession:
    return RetrySession(RetryBudget(max_attempts=max_attempts))


# --- 1. the basics ----------------------------------------------------------


@pytest.mark.unit
def test_no_active_context_is_none():
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_entering_activates_and_exiting_restores_none():
    inner = session()
    with retry_session(inner):
        assert get_active_retry_session() is inner
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_nested_context_restores_the_outer_session():
    outer, inner = session(), session()
    with retry_session(outer):
        assert get_active_retry_session() is outer
        with retry_session(inner):
            assert get_active_retry_session() is inner
        assert get_active_retry_session() is outer
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_reentering_the_same_session_stays_active():
    """A vendor that nests the session it already runs in (yf_retry-style)."""
    active = session()
    with retry_session(active), retry_session(get_active_retry_session()):
        assert get_active_retry_session() is active
    assert get_active_retry_session() is None


# --- 2. every exit path restores --------------------------------------------


@pytest.mark.unit
def test_an_exception_inside_the_block_restores_the_outer_session():
    outer = session()
    with retry_session(outer):
        with (
            pytest.raises(RuntimeError),
            retry_session(session()),
        ):
            raise RuntimeError("vendor bug")
        assert get_active_retry_session() is outer
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_a_cancellation_unwinds_the_block():
    active = session()
    with retry_session(active):
        with (
            pytest.raises(asyncio.CancelledError),
            retry_session(session()),
        ):
            raise asyncio.CancelledError()
        assert get_active_retry_session() is active
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_a_keyboard_interrupt_unwinds_the_block():
    """``KeyboardInterrupt`` is not a normal exit; the session must still go."""
    with (
        pytest.raises(KeyboardInterrupt),
        retry_session(session()),
    ):
        raise KeyboardInterrupt()
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_an_exit_restores_instead_of_popping_a_foreign_session():
    """Interleaved blocks must not pop each other's entries.

    Before the context went per execution context, two threads alternating
    entry/exit on a shared list could pop the *other* thread's session. Here an
    exception unwinds this block while a token-based restore is guaranteed to
    leave the outer value intact.
    """
    outer = session()
    with retry_session(outer):
        with (
            pytest.raises(ValueError),
            retry_session(session()),
        ):
            raise ValueError("fails on exit")
        assert get_active_retry_session() is outer


# --- 3. threads -------------------------------------------------------------


@pytest.mark.unit
def test_a_new_thread_starts_without_a_session():
    """No budget is guessed or copied into a thread nobody gave one to."""
    with retry_session(session()):
        seen = []
        done = threading.Event()

        def worker():
            try:
                seen.append(get_active_retry_session())
            finally:
                done.set()

        thread = threading.Thread(target=worker)
        thread.start()
        assert done.wait(_JOIN_TIMEOUT), "worker thread did not finish"
        thread.join(_JOIN_TIMEOUT)
        assert seen == [None]
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_interleaved_threads_each_see_their_own_session():
    """Both threads enter and read while the other is inside its block.

    A ``Barrier(2)`` after each entry guarantees the pessimistic interleaving:
    neither thread's lookup can run before the other has entered.
    """
    a, b = session(), session()
    entered = threading.Barrier(2, timeout=_JOIN_TIMEOUT)
    seen: dict[str, list] = {"a": [], "b": []}
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(name, own):
        try:
            with retry_session(own):
                first = get_active_retry_session()
                entered.wait()  # both are inside now
                second = get_active_retry_session()
            after_exit = get_active_retry_session()
            with lock:
                seen[name] = [first, second, after_exit]
        except BaseException as exc:  # surfaced by the assertion below
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("a", a)),
        threading.Thread(target=worker, args=("b", b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"

    assert not errors, errors
    assert seen["a"] == [a, a, None]
    assert seen["b"] == [b, b, None]


@pytest.mark.unit
def test_one_thread_exiting_does_not_clear_another_threads_session():
    """B exits (its ``None`` is its own); A is still inside and still sees A."""
    a, b = session(), session()
    a_entered = threading.Event()
    b_done = threading.Event()
    seen_a_after_b = []
    errors: list[BaseException] = []

    def hold_a():
        try:
            with retry_session(a):
                a_entered.set()
                if not b_done.wait(_JOIN_TIMEOUT):
                    raise TimeoutError("thread B never exited")
                seen_a_after_b.append(get_active_retry_session())
            seen_a_after_b.append(get_active_retry_session())
        except BaseException as exc:
            errors.append(exc)

    def enter_and_leave_b():
        try:
            if not a_entered.wait(_JOIN_TIMEOUT):
                raise TimeoutError("thread A never entered")
            with retry_session(b):
                assert get_active_retry_session() is b
        finally:
            b_done.set()

    threads = [threading.Thread(target=hold_a), threading.Thread(target=enter_and_leave_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(_JOIN_TIMEOUT)
        assert not thread.is_alive(), "worker thread hung"

    assert not errors, errors
    assert seen_a_after_b == [a, None]
    assert get_active_retry_session() is None


# --- 4. asyncio: tasks in one thread ---------------------------------------


@pytest.mark.unit
def test_asyncio_tasks_in_one_loop_are_isolated():
    """One event loop, two tasks that interleave at an ``await`` inside the block."""
    a, b = session(), session()
    entered = asyncio.Barrier(2)

    async def worker(name, own):
        with retry_session(own):
            first = get_active_retry_session()
            await entered.wait()  # both tasks are inside their blocks
            second = get_active_retry_session()
        return name, first, second, get_active_retry_session()

    async def main():
        return await asyncio.gather(worker("a", a), worker("b", b))

    results = {}
    for name, first, second, after in asyncio.run(main()):
        results[name] = (first, second, after)

    assert results["a"] == (a, a, None)
    assert results["b"] == (b, b, None)
    assert get_active_retry_session() is None


@pytest.mark.unit
def test_a_new_context_is_not_given_the_session_unless_it_is_copied():
    """A fresh context starts with no session; ``copy_context`` inherits it.

    A new ``contextvars.Context`` started from inside an active block has no
    session; one derived with ``copy_context`` sees the same session object.
    That inheritance is *not* a second budget: ``copy_context`` is shallow, so
    the copied context holds the very same ``RetrySession`` (covered by the
    identity assertion below), and concurrent writers in copied contexts would
    still share and mutate one budget.

    A thread behaves differently (``threading.Thread`` runs in a new, empty
    context), which the thread tests above pin with a real thread and a
    ``Barrier``.
    """
    parent = session()
    reads = {}

    async def read():
        return get_active_retry_session()

    with retry_session(parent):
        reads["fresh"] = contextvars.Context().run(asyncio.run, read())
        reads["copied"] = contextvars.copy_context().run(asyncio.run, read())

    assert reads == {"fresh": None, "copied": parent}
    assert reads["copied"] is parent  # shallow copy: same mutable object
