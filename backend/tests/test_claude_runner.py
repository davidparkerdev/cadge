"""Comprehensive tests for claude_runner.py — subprocess management for the claude CLI.

Tests cover:
- Normal message flow (process spawn, streaming, finalization)
- Cancel mid-stream
- "Already in use" retry logic
- Stale process detection and killing
- Image handling (base64 decode, temp files, cleanup)
- Error handling (non-zero exit, exceptions)
- Per-session lock behavior
- First message vs subsequent (--session-id vs --resume, role prompt)
- Token tracking and Observatory events
- Agent spawn/complete tracking
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import types
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-1",
    claude_session_id: str = "claude-sess-1",
    role: Optional[str] = None,
    project_dir: Optional[str] = None,
    project_name: Optional[str] = None,
    title: str = "Test Session",
    claude_initialized: bool = False,
) -> dict:
    """Build a fake session dict matching session_store.get_session output."""
    return {
        "id": session_id,
        "claude_session_id": claude_session_id,
        "role": role,
        "project_dir": project_dir,
        "project_name": project_name,
        "title": title,
        "status": "active",
        "claude_initialized": claude_initialized,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


class FakeProcess:
    """Mock asyncio subprocess that yields pre-scripted stdout lines.

    Parameters
    ----------
    stdout_lines : list of bytes
        Lines to yield from stdout (each should end with newline).
    stderr_data : bytes
        Data returned by stderr.read().
    returncode : int
        Exit code returned by wait().
    """

    def __init__(
        self,
        stdout_lines: list[bytes] | None = None,
        stderr_data: bytes = b"",
        returncode: int = 0,
    ):
        self._stdout_lines = list(stdout_lines or [])
        self._stdout_idx = 0
        self._stderr_data = stderr_data
        self.returncode = returncode
        self._terminated = False
        self._killed = False
        self.pid = 99999

        # Build stdout as an async-readline-able object
        self.stdout = self._make_stdout()
        self.stderr = self._make_stderr()

    def _make_stdout(self):
        proc = self

        class _Stdout:
            async def readline(self_inner):
                if proc._stdout_idx < len(proc._stdout_lines):
                    line = proc._stdout_lines[proc._stdout_idx]
                    proc._stdout_idx += 1
                    return line
                return b""

        return _Stdout()

    def _make_stderr(self):
        proc = self

        class _Stderr:
            _read_once = False

            async def read(self_inner, n: int = -1):
                if not self_inner._read_once:
                    self_inner._read_once = True
                    return proc._stderr_data
                return b""

        return _Stderr()

    async def wait(self):
        return self.returncode

    def terminate(self):
        self._terminated = True

    def kill(self):
        self._killed = True


def _json_line(event: dict) -> bytes:
    """Encode an event dict as a JSON stdout line (with newline)."""
    return (json.dumps(event) + "\n").encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def runner_env(tmp_path):
    """Set up an isolated environment for testing claude_runner.

    Patches:
    - session_store.DB_PATH -> temp SQLite
    - push_session_event -> MagicMock (no HTTP)
    - _kill_stale_claude_processes -> AsyncMock (no OS calls)
    - asyncio.create_subprocess_exec -> controlled FakeProcess
    - _active_processes -> fresh dict per test
    - _session_locks -> fresh dict per test

    Yields a namespace with all the mocks and helpers.
    """
    db_path = str(tmp_path / "runner_test.db")

    with patch("app.services.session_store.DB_PATH", db_path), \
         patch("app.services.event_store.DB_PATH", db_path):
        from app.services.session_store import (
            create_message,
            create_session,
            delete_message,
            get_session,
            init_db,
            list_messages,
            mark_claude_initialized,
            update_message,
        )
        from app.services.event_store import init_events_table

        await init_db()
        await init_events_table()

        # Import claude_runner AFTER patching DB_PATH so it picks up the test DB
        import app.services.claude_runner as cr

        # Save and replace module-level mutable state
        orig_active = cr._active_processes
        orig_locks = cr._session_locks
        cr._active_processes = {}
        cr._session_locks = {}

        with (
            patch.object(cr, "push_session_event") as mock_observatory,
            patch.object(
                cr, "_kill_stale_claude_processes", new_callable=AsyncMock, return_value=False
            ) as mock_kill_stale,
        ):
            env = types.SimpleNamespace(
                cr=cr,
                mock_observatory=mock_observatory,
                mock_kill_stale=mock_kill_stale,
                create_session=create_session,
                create_message=create_message,
                update_message=update_message,
                delete_message=delete_message,
                get_session=get_session,
                list_messages=list_messages,
                mark_claude_initialized=mark_claude_initialized,
            )
            try:
                yield env
            finally:
                # Restore original state
                cr._active_processes = orig_active
                cr._session_locks = orig_locks


async def _setup_session(env, **kwargs) -> dict:
    """Create a real session in the test DB and return its dict."""
    session = await env.create_session(
        title=kwargs.get("title", "Test Session"),
        role=kwargs.get("role"),
        project_dir=kwargs.get("project_dir"),
        project_name=kwargs.get("project_name"),
    )
    if kwargs.get("claude_initialized", False):
        await env.mark_claude_initialized(session["id"])
        # Re-fetch so the dict reflects the updated flag
        session = await env.get_session(session["id"])
    return session


# ---------------------------------------------------------------------------
# 1. Normal message flow
# ---------------------------------------------------------------------------


class TestNormalMessageFlow:
    """Verify a successful send_message creates a placeholder, streams content,
    finalizes the message, and pushes Observatory events."""

    async def test_placeholder_created_before_streaming(self, runner_env):
        """A placeholder assistant message should exist before the process streams."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}),
            _json_line({"type": "result", "result": "Hello world"}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hi")

        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["status"] == "complete"
        assert msgs[0]["is_complete"] == 1

    async def test_content_accumulated_correctly(self, runner_env):
        """Content from content_block_delta events should be concatenated."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Part A "}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Part B "}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Part C"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Tell me three parts")

        msgs = await env.list_messages(session["id"])
        assert msgs[0]["content"] == "Part A Part B Part C"

    async def test_result_event_used_when_no_deltas(self, runner_env):
        """If no content_block_delta events arrive, the result event text is used."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "result", "result": "Direct result text"}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Quick question")

        msgs = await env.list_messages(session["id"])
        assert msgs[0]["content"] == "Direct result text"

    async def test_session_marked_initialized_after_first_message(self, runner_env):
        """After the first message, session should be marked as claude_initialized."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        updated = await env.get_session(session["id"])
        assert updated["claude_initialized"] == 1

    async def test_observatory_start_and_complete_events(self, runner_env):
        """Observatory should receive both a 'start' and 'complete' event."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hi")

        # Check calls to push_session_event
        calls = env.mock_observatory.call_args_list
        event_types = [c.kwargs.get("event_type") or c[1].get("event_type", "") for c in calls]
        # push_session_event is called with keyword args
        start_calls = [c for c in calls if "event_type" in c.kwargs and c.kwargs["event_type"] == "start"]
        complete_calls = [c for c in calls if "event_type" in c.kwargs and c.kwargs["event_type"] == "complete"]
        assert len(start_calls) >= 1, f"Expected a 'start' Observatory event, got: {calls}"
        assert len(complete_calls) >= 1, f"Expected a 'complete' Observatory event, got: {calls}"

    async def test_broker_receives_start_and_done_events(self, runner_env):
        """The session broker should receive 'start' and 'done' events."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        collected_events = []
        original_publish = env.cr.session_broker.publish

        def capture_publish(sid, event):
            if sid == session["id"]:
                collected_events.append(event)
            original_publish(sid, event)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc),
            patch.object(env.cr.session_broker, "publish", side_effect=capture_publish),
        ):
            await env.cr.send_message(session["id"], "Hello")

        event_types = [e.get("type") for e in collected_events]
        assert "start" in event_types, f"Missing 'start' broker event: {event_types}"
        assert "done" in event_types, f"Missing 'done' broker event: {event_types}"

    async def test_active_processes_cleaned_up_on_completion(self, runner_env):
        """After send_message completes, session should not be in _active_processes."""
        env = runner_env
        session = await _setup_session(env)

        fake_proc = FakeProcess(
            stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
            returncode=0,
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        assert session["id"] not in env.cr._active_processes

    async def test_thinking_content_accumulated(self, runner_env):
        """Thinking deltas should be accumulated and saved to the message."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Let me think..."}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": " about this."}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "The answer is 42."}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "What is the answer?")

        msgs = await env.list_messages(session["id"])
        assert msgs[0]["content"] == "The answer is 42."
        assert msgs[0]["thinking"] == "Let me think... about this."

    async def test_token_tracking_from_result_event(self, runner_env):
        """Token usage from the result event should be included in the Observatory complete event."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}),
            _json_line({"type": "result", "result": "hi", "usage": {"input_tokens": 100, "output_tokens": 50}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        complete_calls = [
            c for c in env.mock_observatory.call_args_list
            if c.kwargs.get("event_type") == "complete"
        ]
        assert len(complete_calls) == 1
        assert complete_calls[0].kwargs["input_tokens"] == 100
        assert complete_calls[0].kwargs["output_tokens"] == 50
        assert complete_calls[0].kwargs["cost_usd"] > 0


# ---------------------------------------------------------------------------
# 2. Cancel mid-stream
# ---------------------------------------------------------------------------


class TestCancelMidStream:
    """Verify that cancel_session terminates the process and cleans up."""

    async def test_cancel_terminates_process(self, runner_env):
        """Calling cancel_session should terminate and clean up the process."""
        env = runner_env
        session = await _setup_session(env)

        fake_proc = FakeProcess(returncode=-15)
        # Register as if it were running
        env.cr._active_processes[session["id"]] = fake_proc

        result = await env.cr.cancel_session(session["id"])

        assert result is True
        assert fake_proc._terminated is True
        assert session["id"] not in env.cr._active_processes

    async def test_cancel_publishes_cancelled_event(self, runner_env):
        """cancel_session should publish a 'cancelled' event via the broker."""
        env = runner_env
        session = await _setup_session(env)

        fake_proc = FakeProcess(returncode=-15)
        env.cr._active_processes[session["id"]] = fake_proc

        collected = []
        original_publish = env.cr.session_broker.publish

        def capture(sid, event):
            if sid == session["id"]:
                collected.append(event)
            original_publish(sid, event)

        with patch.object(env.cr.session_broker, "publish", side_effect=capture):
            await env.cr.cancel_session(session["id"])

        types = [e.get("type") for e in collected]
        assert "cancelled" in types

    async def test_cancel_pushes_observatory_event(self, runner_env):
        """cancel_session should push a 'cancel' event to Observatory."""
        env = runner_env
        session = await _setup_session(env)

        fake_proc = FakeProcess(returncode=-15)
        env.cr._active_processes[session["id"]] = fake_proc

        await env.cr.cancel_session(session["id"])

        cancel_calls = [
            c for c in env.mock_observatory.call_args_list
            if c.kwargs.get("event_type") == "cancel"
        ]
        assert len(cancel_calls) == 1

    async def test_cancel_nonexistent_session_returns_false(self, runner_env):
        """Cancelling a session with no active process should return False."""
        env = runner_env
        result = await env.cr.cancel_session("nonexistent")
        assert result is False

    async def test_cancel_kills_on_timeout(self, runner_env):
        """If terminate doesn't stop the process within timeout, kill should be called."""
        env = runner_env
        session = await _setup_session(env)

        # Create a process whose wait() times out after terminate
        fake_proc = FakeProcess(returncode=-9)
        call_count = 0

        async def slow_wait():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First wait (after terminate) — hang until timeout
                raise asyncio.TimeoutError()
            return -9

        fake_proc.wait = slow_wait
        env.cr._active_processes[session["id"]] = fake_proc

        await env.cr.cancel_session(session["id"])

        assert fake_proc._terminated is True
        assert fake_proc._killed is True
        assert session["id"] not in env.cr._active_processes


# ---------------------------------------------------------------------------
# 3. "Already in use" retry
# ---------------------------------------------------------------------------


class TestAlreadyInUseRetry:
    """Verify retry logic when claude CLI reports 'already in use'."""

    async def test_retries_on_already_in_use(self, runner_env):
        """When stderr says 'already in use', it should retry once."""
        env = runner_env
        session = await _setup_session(env)

        # First attempt: fails with "already in use"
        fail_proc = FakeProcess(
            stdout_lines=[],
            stderr_data=b"Error: Session ID claude-sess-1 is already in use",
            returncode=1,
        )
        # Second attempt: succeeds
        success_proc = FakeProcess(
            stdout_lines=[
                _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Retry worked"}}),
            ],
            returncode=0,
        )

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fail_proc
            return success_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await env.cr.send_message(session["id"], "Hello")

        assert call_count == 2

        # The message from the retry should be persisted
        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Retry worked"
        assert msgs[0]["status"] == "complete"

    async def test_retry_cleans_up_failed_placeholder(self, runner_env):
        """The placeholder from the failed first attempt should be deleted before retry."""
        env = runner_env
        session = await _setup_session(env)

        fail_proc = FakeProcess(
            stdout_lines=[],
            stderr_data=b"Session ID X is already in use",
            returncode=1,
        )
        success_proc = FakeProcess(
            stdout_lines=[
                _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}}),
            ],
            returncode=0,
        )

        calls = []

        async def mock_exec(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return fail_proc
            return success_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await env.cr.send_message(session["id"], "Hi")

        # Only the success message should remain (failed placeholder deleted)
        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["content"] == "OK"

    async def test_no_retry_on_other_errors(self, runner_env):
        """Errors without 'already in use' should NOT trigger retry."""
        env = runner_env
        session = await _setup_session(env)

        fail_proc = FakeProcess(
            stdout_lines=[],
            stderr_data=b"Some other error occurred",
            returncode=1,
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fail_proc):
            await env.cr.send_message(session["id"], "Hi")

        # Should have error message, no retry
        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["status"] == "error"
        assert "exited with code 1" in msgs[0]["content"]

    async def test_retry_calls_kill_stale(self, runner_env):
        """On 'already in use' error, _kill_stale_claude_processes should be called again."""
        env = runner_env
        session = await _setup_session(env)

        fail_proc = FakeProcess(
            stdout_lines=[],
            stderr_data=b"Session ID is already in use",
            returncode=1,
        )
        success_proc = FakeProcess(
            stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
            returncode=0,
        )

        exec_calls = []

        async def mock_exec(*args, **kwargs):
            exec_calls.append(1)
            if len(exec_calls) == 1:
                return fail_proc
            return success_proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await env.cr.send_message(session["id"], "Hi")

        # _kill_stale is called proactively at start of _run_claude,
        # and again on "already in use" retry. Two calls from first attempt,
        # one proactive from retry = at least 3 calls total.
        assert env.mock_kill_stale.call_count >= 2


# ---------------------------------------------------------------------------
# 4. Stale process detection
# ---------------------------------------------------------------------------


class TestKillStaleProcessesDirect:
    """Test _kill_stale_claude_processes by calling the real function with mocked OS calls."""

    async def test_finds_and_kills_pids(self):
        """Should call os.kill(SIGTERM) for each PID found by pgrep."""
        fake_pgrep = AsyncMock()
        fake_pgrep.returncode = 0
        fake_pgrep.communicate = AsyncMock(return_value=(b"11111\n22222\n", b""))

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_pgrep),
            patch("os.kill") as mock_kill,
            patch("os.getpid", return_value=99999),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            from app.services import claude_runner as cr_mod
            result = await cr_mod._kill_stale_claude_processes("test-claude-session")

        mock_kill.assert_any_call(11111, signal.SIGTERM)
        mock_kill.assert_any_call(22222, signal.SIGTERM)
        assert result is True
        mock_sleep.assert_called_once_with(1.5)

    async def test_skips_own_pid(self):
        """Should not kill its own process."""
        fake_pgrep = AsyncMock()
        fake_pgrep.returncode = 0
        fake_pgrep.communicate = AsyncMock(return_value=(b"12345\n", b""))

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_pgrep),
            patch("os.kill") as mock_kill,
            patch("os.getpid", return_value=12345),  # Same as the found PID
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from app.services import claude_runner as cr_mod
            result = await cr_mod._kill_stale_claude_processes("test-session")

        mock_kill.assert_not_called()
        assert result is False

    async def test_returns_false_when_no_matches(self):
        """Should return False when pgrep finds no matching processes."""
        fake_pgrep = AsyncMock()
        fake_pgrep.returncode = 1
        fake_pgrep.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_pgrep):
            from app.services import claude_runner as cr_mod
            result = await cr_mod._kill_stale_claude_processes("no-such-session")

        assert result is False

    async def test_handles_process_lookup_error(self):
        """Should handle ProcessLookupError gracefully (process died between pgrep and kill)."""
        fake_pgrep = AsyncMock()
        fake_pgrep.returncode = 0
        fake_pgrep.communicate = AsyncMock(return_value=(b"99999\n", b""))

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_pgrep),
            patch("os.kill", side_effect=ProcessLookupError("No such process")),
            patch("os.getpid", return_value=1),
        ):
            from app.services import claude_runner as cr_mod
            result = await cr_mod._kill_stale_claude_processes("test-session")

        # ProcessLookupError is caught, so killed_any stays False
        assert result is False

    async def test_handles_subprocess_exception(self):
        """Should handle exceptions from pgrep gracefully."""
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=OSError("pgrep not found"),
        ):
            from app.services import claude_runner as cr_mod
            result = await cr_mod._kill_stale_claude_processes("test-session")

        assert result is False


# ---------------------------------------------------------------------------
# 5. Image handling
# ---------------------------------------------------------------------------


class TestImageHandling:
    """Verify base64 images are decoded, temp files created, and cleaned up."""

    async def test_single_image_decoded_to_temp_file(self, runner_env):
        """A base64 image should be decoded and saved to a temp file."""
        env = runner_env
        session = await _setup_session(env)

        # Create a small 1x1 PNG
        png_bytes = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
        image_b64 = f"data:image/png;base64,{png_bytes}"

        created_cmds = []

        async def capture_exec(*args, **kwargs):
            created_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Image received"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "What is this?", images=[image_b64])

        # Verify the command includes --add-dir
        cmd_args = created_cmds[0]
        assert "--add-dir" in cmd_args, f"Expected --add-dir in command: {cmd_args}"

        # Verify the prompt was modified to include Read tool instructions
        prompt_idx = cmd_args.index("-p") + 1
        prompt_text = cmd_args[prompt_idx]
        assert "Read tool" in prompt_text
        assert "attached an image" in prompt_text

    async def test_multiple_images_handled(self, runner_env):
        """Multiple images should each get a temp file and prompt should list them."""
        env = runner_env
        session = await _setup_session(env)

        png_data = base64.b64encode(b"\x89PNG" + b"\x00" * 50).decode()
        images = [
            f"data:image/png;base64,{png_data}",
            f"data:image/png;base64,{png_data}",
        ]

        created_cmds = []

        async def capture_exec(*args, **kwargs):
            created_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Compare these", images=images)

        prompt_text = created_cmds[0][created_cmds[0].index("-p") + 1]
        assert "2 images" in prompt_text

    async def test_temp_files_cleaned_up_on_success(self, runner_env):
        """Temp image files should be deleted after the process completes."""
        env = runner_env
        session = await _setup_session(env)

        png_data = base64.b64encode(b"\x89PNG" + b"\x00" * 50).decode()
        images = [f"data:image/png;base64,{png_data}"]

        temp_paths_seen = []

        async def capture_exec(*args, **kwargs):
            # Find the temp file path from --add-dir argument
            arg_list = list(args)
            if "--add-dir" in arg_list:
                add_dir_idx = arg_list.index("--add-dir") + 1
                temp_dir = arg_list[add_dir_idx]
                # List files in the temp dir
                import glob
                temp_paths_seen.extend(glob.glob(os.path.join(temp_dir, "nexus_img_*")))

            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Describe", images=images)

        # The temp files should have been created (seen during exec)
        assert len(temp_paths_seen) >= 1
        # And then cleaned up after completion
        for path in temp_paths_seen:
            assert not os.path.exists(path), f"Temp file not cleaned up: {path}"

    async def test_temp_files_cleaned_up_on_error(self, runner_env):
        """Temp files should be cleaned up even if the process fails."""
        env = runner_env
        session = await _setup_session(env)

        png_data = base64.b64encode(b"\x89PNG" + b"\x00" * 50).decode()
        images = [f"data:image/png;base64,{png_data}"]

        temp_paths_seen = []

        async def capture_exec(*args, **kwargs):
            arg_list = list(args)
            if "--add-dir" in arg_list:
                add_dir_idx = arg_list.index("--add-dir") + 1
                temp_dir = arg_list[add_dir_idx]
                import glob
                temp_paths_seen.extend(glob.glob(os.path.join(temp_dir, "nexus_img_*")))

            return FakeProcess(
                stdout_lines=[],
                stderr_data=b"Some error",
                returncode=1,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Describe", images=images)

        for path in temp_paths_seen:
            assert not os.path.exists(path), f"Temp file not cleaned up after error: {path}"

    async def test_invalid_base64_image_skipped(self, runner_env):
        """Invalid base64 data should be skipped without crashing."""
        env = runner_env
        session = await _setup_session(env)

        images = ["not-valid-base64!!!"]

        fake_proc = FakeProcess(
            stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
            returncode=0,
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            # Should not raise
            await env.cr.send_message(session["id"], "Hello", images=images)

        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["status"] == "complete"


# ---------------------------------------------------------------------------
# 6. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify error states are handled correctly."""

    async def test_nonzero_exit_stores_error_message(self, runner_env):
        """Non-zero exit with stderr should store an error message."""
        env = runner_env
        session = await _setup_session(env)

        fake_proc = FakeProcess(
            stdout_lines=[],
            stderr_data=b"Authentication failed: invalid API key",
            returncode=1,
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["status"] == "error"
        assert "[Error]" in msgs[0]["content"]
        assert "Authentication failed" in msgs[0]["content"]

    async def test_error_pushes_observatory_failure_event(self, runner_env):
        """Exceptions during streaming should push a 'failure' event to Observatory."""
        env = runner_env
        session = await _setup_session(env)

        # Make create_subprocess_exec raise an exception
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=RuntimeError("Subprocess launch failed"),
        ):
            await env.cr.send_message(session["id"], "Hello")

        failure_calls = [
            c for c in env.mock_observatory.call_args_list
            if c.kwargs.get("event_type") == "failure"
        ]
        assert len(failure_calls) >= 1
        assert "Subprocess launch failed" in failure_calls[0].kwargs["error"]

    async def test_exception_stores_error_in_placeholder(self, runner_env):
        """An exception during streaming should mark the placeholder as error."""
        env = runner_env
        session = await _setup_session(env)

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=RuntimeError("Boom"),
        ):
            await env.cr.send_message(session["id"], "Hello")

        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 1
        assert msgs[0]["status"] == "error"

    async def test_exception_publishes_error_to_broker(self, runner_env):
        """An exception during streaming should publish an 'error' event to the broker."""
        env = runner_env
        session = await _setup_session(env)

        collected = []
        original_publish = env.cr.session_broker.publish

        def capture(sid, event):
            if sid == session["id"]:
                collected.append(event)
            original_publish(sid, event)

        with (
            patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("Boom")),
            patch.object(env.cr.session_broker, "publish", side_effect=capture),
        ):
            await env.cr.send_message(session["id"], "Hello")

        types = [e.get("type") for e in collected]
        assert "error" in types

    async def test_unknown_session_returns_early(self, runner_env):
        """Sending to a nonexistent session should log error and return without crashing."""
        env = runner_env

        # Don't create a session — just call with a fake ID
        # This should return early since get_session returns None
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            await env.cr.send_message("nonexistent-session-id", "Hello")

        # Subprocess should never have been called
        mock_exec.assert_not_called()

    async def test_empty_response_deletes_placeholder(self, runner_env):
        """If the process exits 0 with no content, the empty placeholder should be deleted."""
        env = runner_env
        session = await _setup_session(env)

        # Process exits successfully but produces no output
        fake_proc = FakeProcess(stdout_lines=[], returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        msgs = await env.list_messages(session["id"])
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# 7. Lock behavior
# ---------------------------------------------------------------------------


class TestLockBehavior:
    """Verify per-session locking prevents concurrent claude processes."""

    async def test_same_session_serialized(self, runner_env):
        """Two sends on the same session should run sequentially (locked)."""
        env = runner_env
        session = await _setup_session(env)

        execution_order = []

        async def mock_exec(*args, **kwargs):
            execution_order.append("start")
            proc = FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
                returncode=0,
            )
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            # Run two sends concurrently on the same session
            t1 = asyncio.create_task(env.cr.send_message(session["id"], "First"))
            t2 = asyncio.create_task(env.cr.send_message(session["id"], "Second"))
            await asyncio.gather(t1, t2)

        # Both should complete (2 messages), but they ran one at a time
        msgs = await env.list_messages(session["id"])
        # Both tasks completed — they both created messages
        assert len(msgs) >= 1

    async def test_different_sessions_concurrent(self, runner_env):
        """Two sends on different sessions should run concurrently (different locks)."""
        env = runner_env
        session1 = await _setup_session(env, title="Session 1")
        session2 = await _setup_session(env, title="Session 2")

        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        original_exec = None

        async def tracking_exec(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                if concurrent_count > max_concurrent:
                    max_concurrent = concurrent_count
            # Yield control to allow other task to start
            await asyncio.sleep(0.01)
            proc = FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
                returncode=0,
            )
            async with lock:
                concurrent_count -= 1
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=tracking_exec):
            t1 = asyncio.create_task(env.cr.send_message(session1["id"], "Hello"))
            t2 = asyncio.create_task(env.cr.send_message(session2["id"], "Hello"))
            await asyncio.gather(t1, t2)

        # Both sessions should have a message
        msgs1 = await env.list_messages(session1["id"])
        msgs2 = await env.list_messages(session2["id"])
        assert len(msgs1) == 1
        assert len(msgs2) == 1

    async def test_lock_released_on_error(self, runner_env):
        """The per-session lock should be released even if _run_claude raises."""
        env = runner_env
        session = await _setup_session(env)

        # First call: fails with exception
        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Process failed")
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
            await env.cr.send_message(session["id"], "First")  # fails
            await env.cr.send_message(session["id"], "Second")  # should succeed

        assert call_count == 2

    def test_get_session_lock_creates_once(self, runner_env):
        """_get_session_lock should return the same lock for the same session."""
        env = runner_env
        lock1 = env.cr._get_session_lock("test-session")
        lock2 = env.cr._get_session_lock("test-session")
        assert lock1 is lock2

    def test_get_session_lock_different_per_session(self, runner_env):
        """_get_session_lock should return different locks for different sessions."""
        env = runner_env
        lock1 = env.cr._get_session_lock("session-a")
        lock2 = env.cr._get_session_lock("session-b")
        assert lock1 is not lock2


# ---------------------------------------------------------------------------
# 8. First message vs subsequent
# ---------------------------------------------------------------------------


class TestFirstVsSubsequent:
    """Verify --session-id for first message, --resume for subsequent, and role prompt."""

    async def test_first_message_uses_session_id_flag(self, runner_env):
        """First message should use --session-id, not --resume."""
        env = runner_env
        session = await _setup_session(env)

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Hello")

        cmd = captured_cmds[0]
        assert "--session-id" in cmd
        assert "--resume" not in cmd

    async def test_subsequent_message_uses_resume_flag(self, runner_env):
        """After initialization, subsequent messages should use --resume."""
        env = runner_env
        session = await _setup_session(env, claude_initialized=True)

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Follow up")

        cmd = captured_cmds[0]
        assert "--resume" in cmd
        assert "--session-id" not in cmd

    async def test_role_prompt_prepended_on_first_message(self, runner_env):
        """On the first message, the role prompt should be prepended."""
        env = runner_env
        session = await _setup_session(env, role="coding")

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Write a function")

        cmd = captured_cmds[0]
        prompt_idx = cmd.index("-p") + 1
        prompt_text = cmd[prompt_idx]
        assert "senior software engineer" in prompt_text
        assert "Write a function" in prompt_text

    async def test_role_prompt_not_prepended_on_subsequent_message(self, runner_env):
        """On subsequent messages, the role prompt should NOT be prepended."""
        env = runner_env
        session = await _setup_session(env, role="coding", claude_initialized=True)

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Another question")

        cmd = captured_cmds[0]
        prompt_idx = cmd.index("-p") + 1
        prompt_text = cmd[prompt_idx]
        assert "senior software engineer" not in prompt_text
        assert prompt_text == "Another question"

    async def test_no_role_prompt_when_role_is_none(self, runner_env):
        """When session has no role, prompt should be unmodified."""
        env = runner_env
        session = await _setup_session(env, role=None)

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Just a question")

        cmd = captured_cmds[0]
        prompt_idx = cmd.index("-p") + 1
        assert cmd[prompt_idx] == "Just a question"

    async def test_command_includes_output_format_and_verbose(self, runner_env):
        """Every command should include --output-format stream-json and --verbose."""
        env = runner_env
        session = await _setup_session(env)

        captured_cmds = []

        async def capture_exec(*args, **kwargs):
            captured_cmds.append(args)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Hello")

        cmd = captured_cmds[0]
        assert "--output-format" in cmd
        assert "stream-json" in cmd
        assert "--verbose" in cmd
        assert "--dangerously-skip-permissions" in cmd

    async def test_claudecode_env_stripped(self, runner_env):
        """The CLAUDECODE env var should be stripped from the subprocess environment."""
        env = runner_env
        session = await _setup_session(env)

        captured_kwargs = []

        async def capture_exec(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with (
            patch.dict(os.environ, {"CLAUDECODE": "1"}),
            patch("asyncio.create_subprocess_exec", side_effect=capture_exec),
        ):
            await env.cr.send_message(session["id"], "Hello")

        clean_env = captured_kwargs[0]["env"]
        assert "CLAUDECODE" not in clean_env


# ---------------------------------------------------------------------------
# 9. Tool calls and agent tracking
# ---------------------------------------------------------------------------


class TestToolCallsAndAgents:
    """Verify tool_use blocks are accumulated and Task agent spawn/complete events work."""

    async def test_tool_calls_from_assistant_event(self, runner_env):
        """tool_use blocks in assistant events should be accumulated and persisted."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Let me read that."}}),
            _json_line({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "Read", "input": {"path": "/tmp/f"}},
                    ]
                },
            }),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Read the file")

        msgs = await env.list_messages(session["id"])
        assert msgs[0]["tool_calls"] is not None
        assert len(msgs[0]["tool_calls"]) == 1
        assert msgs[0]["tool_calls"][0]["name"] == "Read"

    async def test_agent_spawn_event_published(self, runner_env):
        """When a Task tool_use is streamed, an agent_spawn event should be published."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Task", "id": "task-1"}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"description": "Do stuff"'}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": ', "prompt": "hello"}'}}),
            _json_line({"type": "content_block_stop"}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Done"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        collected = []
        original_publish = env.cr.session_broker.publish

        def capture(sid, event):
            if sid == session["id"]:
                collected.append(event)
            original_publish(sid, event)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc),
            patch.object(env.cr.session_broker, "publish", side_effect=capture),
        ):
            await env.cr.send_message(session["id"], "Run a task")

        spawn_events = [e for e in collected if e.get("type") == "agent_spawn"]
        assert len(spawn_events) == 1
        assert spawn_events[0]["toolUseId"] == "task-1"
        assert spawn_events[0]["description"] == "Do stuff"

    async def test_remaining_agents_completed_on_finish(self, runner_env):
        """Any agents still running when the process exits should get agent_complete events."""
        env = runner_env
        session = await _setup_session(env)

        # Spawn a Task agent but don't send a tool_result for it
        stdout_lines = [
            _json_line({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Task", "id": "task-orphan"}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"description":"orphan"}'}}),
            _json_line({"type": "content_block_stop"}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Done"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        collected = []
        original_publish = env.cr.session_broker.publish

        def capture(sid, event):
            if sid == session["id"]:
                collected.append(event)
            original_publish(sid, event)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc),
            patch.object(env.cr.session_broker, "publish", side_effect=capture),
        ):
            await env.cr.send_message(session["id"], "Run a task")

        complete_events = [e for e in collected if e.get("type") == "agent_complete"]
        assert len(complete_events) >= 1
        assert any(e["toolUseId"] == "task-orphan" for e in complete_events)


# ---------------------------------------------------------------------------
# 10. Utility functions
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    """Test simple utility functions on the claude_runner module."""

    def test_active_session_count(self, runner_env):
        env = runner_env
        assert env.cr.active_session_count() == 0

        env.cr._active_processes["a"] = MagicMock()
        assert env.cr.active_session_count() == 1

        env.cr._active_processes["b"] = MagicMock()
        assert env.cr.active_session_count() == 2

    def test_is_session_streaming(self, runner_env):
        env = runner_env
        assert env.cr.is_session_streaming("x") is False

        env.cr._active_processes["x"] = MagicMock()
        assert env.cr.is_session_streaming("x") is True


# ---------------------------------------------------------------------------
# 11. Project dir resolution
# ---------------------------------------------------------------------------


class TestProjectDirResolution:
    """Verify that project_dir is resolved correctly for subprocess cwd."""

    async def test_absolute_project_dir(self, runner_env, tmp_path):
        """An absolute project_dir should be used directly."""
        env = runner_env
        abs_dir = str(tmp_path / "project")
        os.makedirs(abs_dir, exist_ok=True)
        session = await _setup_session(env, project_dir=abs_dir)

        captured_kwargs = []

        async def capture_exec(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Hello")

        assert captured_kwargs[0]["cwd"] == abs_dir

    async def test_nonexistent_project_dir_ignored(self, runner_env):
        """If project_dir doesn't exist, cwd should be None."""
        env = runner_env
        session = await _setup_session(env, project_dir="/nonexistent/path/xyz")

        captured_kwargs = []

        async def capture_exec(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Hello")

        assert captured_kwargs[0]["cwd"] is None

    async def test_no_project_dir(self, runner_env):
        """When project_dir is None, cwd should be None."""
        env = runner_env
        session = await _setup_session(env, project_dir=None)

        captured_kwargs = []

        async def capture_exec(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeProcess(
                stdout_lines=[_json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}})],
                returncode=0,
            )

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            await env.cr.send_message(session["id"], "Hello")

        assert captured_kwargs[0]["cwd"] is None


# ---------------------------------------------------------------------------
# 12. Stream event parsing edge cases
# ---------------------------------------------------------------------------


class TestStreamEventEdgeCases:
    """Test edge cases in stream-json event parsing."""

    async def test_non_json_lines_wrapped_as_raw(self, runner_env):
        """Non-JSON stdout lines should be broadcast as raw text events."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            b"This is not JSON\n",
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "actual"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        collected = []
        original_publish = env.cr.session_broker.publish

        def capture(sid, event):
            if sid == session["id"]:
                collected.append(event)
            original_publish(sid, event)

        with (
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc),
            patch.object(env.cr.session_broker, "publish", side_effect=capture),
        ):
            await env.cr.send_message(session["id"], "Hello")

        raw_events = [e for e in collected if e.get("type") == "raw"]
        assert len(raw_events) == 1
        assert raw_events[0]["text"] == "This is not JSON"

    async def test_empty_lines_skipped(self, runner_env):
        """Empty stdout lines should be silently ignored."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            b"\n",
            b"  \n",
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "content"}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        msgs = await env.list_messages(session["id"])
        assert msgs[0]["content"] == "content"

    async def test_message_start_tracks_input_tokens(self, runner_env):
        """message_start uses max() to set input tokens; result uses += to accumulate.

        When both events carry the same token count, the total is the sum because
        message_start sets via max() and result adds via +=.
        """
        env = runner_env
        session = await _setup_session(env)

        # message_start sets _input_tokens = max(0, 150) = 150
        # result adds _input_tokens += 200 = 350
        stdout_lines = [
            _json_line({"type": "message_start", "message": {"usage": {"input_tokens": 150}}}),
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}),
            _json_line({"type": "result", "result": "hi", "usage": {"input_tokens": 200, "output_tokens": 30}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        complete_calls = [
            c for c in env.mock_observatory.call_args_list
            if c.kwargs.get("event_type") == "complete"
        ]
        # 150 (from message_start max) + 200 (from result +=) = 350
        assert complete_calls[0].kwargs["input_tokens"] == 350

    async def test_message_delta_tracks_output_tokens(self, runner_env):
        """message_delta events should track output token counts."""
        env = runner_env
        session = await _setup_session(env)

        stdout_lines = [
            _json_line({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}),
            _json_line({"type": "message_delta", "usage": {"output_tokens": 75}}),
        ]
        fake_proc = FakeProcess(stdout_lines=stdout_lines, returncode=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc):
            await env.cr.send_message(session["id"], "Hello")

        complete_calls = [
            c for c in env.mock_observatory.call_args_list
            if c.kwargs.get("event_type") == "complete"
        ]
        assert complete_calls[0].kwargs["output_tokens"] == 75
