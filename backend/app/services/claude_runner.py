"""Subprocess management for `claude` CLI.

Spawns `claude -p "<prompt>" --session-id <id> --output-format stream-json`
and pipes stdout line-by-line through the StreamBroker so SSE clients
receive events in real time.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
from typing import Optional

from app.services.session_store import (
    create_message,
    get_session,
    list_messages,
    touch_session,
    update_message,
)
from app.services.stream_broker import session_broker

logger = logging.getLogger(__name__)

# Active subprocesses: session_id -> asyncio.subprocess.Process
_active_processes: dict[str, asyncio.subprocess.Process] = {}

# Per-session locks to prevent concurrent claude processes on the same session.
# Without this, two asyncio tasks can both pass the cancel check before either
# has registered its process, causing the second to hit "session already in use".
_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


# Base directory for resolving relative project_dir paths.
# - If NEXUS_PROJECT_ROOT env var is set, use that.
# - Otherwise, default to the backend's parent directory (nexus-v2/).
#   This works both in a monorepo (set env var to monorepo root) and standalone.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.environ.get("NEXUS_PROJECT_ROOT", os.path.dirname(_BACKEND_DIR))

ROLE_PROMPTS = {
    "product": "You are a product manager. Help define product requirements, write user stories, prioritize features, and think through user experience. Focus on user value, feasibility, and clear acceptance criteria.",
    "coding": "You are a senior software engineer. Write clean, well-tested code. Follow existing patterns in the codebase. Think through edge cases.",
    "writing": "You are a skilled writer. Help with clear, concise technical writing, documentation, blog posts, and communication.",
    "deep-dive": "You are a deep research analyst. Thoroughly investigate topics, trace through code paths, and provide comprehensive analysis with evidence.",
    "bug-fixing": "You are a debugging expert. Systematically identify root causes, check logs, trace execution paths, and fix bugs with minimal side effects.",
    "analysis": "You are a data and systems analyst. Analyze patterns, identify bottlenecks, evaluate trade-offs, and provide actionable recommendations.",
    "qa": "You are a QA engineer. Design test cases, find edge cases, verify acceptance criteria, and ensure quality across the feature.",
    "frontend": "You are a frontend design engineer specializing in UX and React. Build responsive, accessible, beautiful interfaces with Tailwind CSS.",
    "web-dev": "You are a full-stack web developer. Build robust APIs, responsive UIs, and reliable infrastructure.",
    "game-dev": "You are a game developer. Design game mechanics, implement gameplay systems, optimize performance, and create engaging experiences.",
    "nextjs": "You are a Next.js expert. Build performant server-rendered React applications with app router, server components, and modern patterns.",
}


def active_session_count() -> int:
    """Return the number of sessions with a running subprocess."""
    return len(_active_processes)


def is_session_streaming(session_id: str) -> bool:
    return session_id in _active_processes


async def send_message(
    session_id: str,
    prompt: str,
    images: Optional[list[str]] = None,
) -> None:
    """Spawn a claude subprocess and stream its output to the broker.

    This is meant to be launched as a background task via asyncio.create_task.
    Uses a per-session lock so only one claude process runs per session at a time.
    """
    lock = _get_session_lock(session_id)

    # If the lock is already held (previous message still running), cancel it
    if lock.locked() and session_id in _active_processes:
        logger.info("Cancelling active process for session %s before sending new message", session_id)
        await cancel_session(session_id)

    async with lock:
        await _run_claude(session_id, prompt, images)


async def _run_claude(
    session_id: str,
    prompt: str,
    images: Optional[list[str]] = None,
) -> None:
    """Inner implementation: spawn claude and stream output."""
    session = await get_session(session_id)
    if not session:
        logger.error("send_message called for unknown session %s", session_id)
        return

    claude_session_id = session["claude_session_id"]
    role = session.get("role")
    project_dir = session.get("project_dir")

    # Check if this session has been used before. First call uses --session-id
    # to create the CLI session; subsequent calls use --resume to continue it
    # (--session-id permanently claims the session and rejects further use).
    # The route handler saves the user message before spawning this task, so
    # for the very first message there's exactly 1 row; for subsequent, 3+.
    existing_messages = await list_messages(session_id, limit=3)
    is_first_message = len(existing_messages) <= 1

    # Prepend role context on the first message if a role is set
    if role and role in ROLE_PROMPTS and is_first_message:
        prompt = f"{ROLE_PROMPTS[role]}\n\n{prompt}"

    # Resolve project_dir to an absolute path for subprocess cwd
    abs_project_dir: str | None = None
    if project_dir:
        if os.path.isabs(project_dir):
            abs_project_dir = project_dir
        else:
            abs_project_dir = os.path.join(PROJECT_ROOT, project_dir)
        if not os.path.isdir(abs_project_dir):
            logger.warning("project_dir %s does not exist, ignoring", abs_project_dir)
            abs_project_dir = None

    # Handle images: decode base64 to temp files, then tell Claude to read them.
    # The claude CLI has no --image flag; instead we save to disk and instruct
    # Claude to use its Read tool (which natively supports image viewing).
    temp_files: list[str] = []
    add_dirs: list[str] = []
    if images:
        image_paths: list[str] = []
        for i, b64 in enumerate(images):
            try:
                data = base64.b64decode(b64)
                suffix = ".png"
                fd, path = tempfile.mkstemp(suffix=suffix, prefix=f"nexus_img_{i}_")
                os.write(fd, data)
                os.close(fd)
                temp_files.append(path)
                image_paths.append(path)
            except Exception:
                logger.exception("Failed to decode image %d", i)

        if image_paths:
            # Grant Claude access to the temp directory
            add_dirs.append(os.path.dirname(image_paths[0]))

            # Prepend image instructions to the prompt
            if len(image_paths) == 1:
                prompt = (
                    f"[The user has attached an image. "
                    f"Use the Read tool to view it at: {image_paths[0]}]\n\n"
                    + prompt
                )
            else:
                paths_list = "\n".join(f"- {p}" for p in image_paths)
                prompt = (
                    f"[The user has attached {len(image_paths)} images. "
                    f"Use the Read tool to view them:\n{paths_list}]\n\n"
                    + prompt
                )

    # Build command (after all prompt modifications)
    cmd = [
        "claude",
        "-p", prompt,
    ]
    if is_first_message:
        cmd.extend(["--session-id", claude_session_id])
    else:
        cmd.extend(["--resume", claude_session_id])
    cmd.extend([
        "--output-format", "stream-json",
        "--verbose",
    ])
    for d in add_dirs:
        cmd.extend(["--add-dir", d])

    # Publish a "start" meta-event so the frontend knows streaming began
    session_broker.publish(session_id, {
        "type": "start",
        "session_id": session_id,
    })

    # Strip CLAUDECODE env var so the CLI doesn't think it's nested
    clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    process: Optional[asyncio.subprocess.Process] = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
            cwd=abs_project_dir,
        )
        _active_processes[session_id] = process

        # Accumulate the final assistant message content
        full_content_parts: list[str] = []
        tool_calls: list[dict] = []
        thinking_parts: list[str] = []

        # Track interactive tool calls for structured events
        current_tool_name: str | None = None
        current_tool_id: str | None = None
        current_tool_json_parts: list[str] = []
        running_agents: dict[str, dict] = {}  # tool_use_id -> agent info

        # Read stdout line by line
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            # Try to parse as JSON
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                # Not JSON -- wrap it as a raw text event
                event = {"type": "raw", "text": text}

            # Broadcast to all SSE subscribers
            session_broker.publish(session_id, event)

            # Accumulate content for persistence
            event_type = event.get("type", "")
            if event_type == "assistant":
                # Full assistant message (streaming chunks or final)
                content = event.get("message", {}).get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                full_content_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                tool_calls.append(block)
                            elif block.get("type") == "thinking":
                                thinking_parts.append(block.get("thinking", ""))
                            elif block.get("type") == "tool_result":
                                tool_use_id = block.get("tool_use_id")
                                if tool_use_id and tool_use_id in running_agents:
                                    result_content = block.get("content", "")
                                    if isinstance(result_content, list):
                                        result_text = " ".join(
                                            b.get("text", "") for b in result_content
                                            if isinstance(b, dict) and b.get("type") == "text"
                                        )
                                    elif isinstance(result_content, str):
                                        result_text = result_content
                                    else:
                                        result_text = str(result_content)
                                    session_broker.publish(session_id, {
                                        "type": "agent_complete",
                                        "toolUseId": tool_use_id,
                                        "result": result_text[:500],
                                        "isError": block.get("is_error", False),
                                    })
                                    running_agents.pop(tool_use_id, None)
                elif isinstance(content, str):
                    full_content_parts.append(content)
            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    full_content_parts.append(delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    thinking_parts.append(delta.get("thinking", ""))
                elif delta.get("type") == "input_json_delta":
                    if delta.get("partial_json"):
                        current_tool_json_parts.append(delta["partial_json"])
            elif event_type == "result":
                # Final result event from stream-json
                result_text = event.get("result", "")
                if result_text and not full_content_parts:
                    full_content_parts.append(result_text)
            elif event_type == "content_block_start":
                cb = event.get("content_block", {})
                if cb.get("type") == "tool_use":
                    current_tool_name = cb.get("name")
                    current_tool_id = cb.get("id")
                    current_tool_json_parts = []
            elif event_type == "content_block_stop":
                if current_tool_name == "Task" and current_tool_id:
                    try:
                        full_json = "".join(current_tool_json_parts)
                        tool_input = json.loads(full_json) if full_json else {}
                    except json.JSONDecodeError:
                        tool_input = {}
                    agent_info = {
                        "toolUseId": current_tool_id,
                        "description": tool_input.get("description", "Sub-agent task"),
                        "subagentType": tool_input.get("subagent_type", "Task"),
                        "prompt": tool_input.get("prompt", ""),
                    }
                    running_agents[current_tool_id] = agent_info
                    session_broker.publish(session_id, {
                        "type": "agent_spawn",
                        **agent_info,
                    })
                current_tool_name = None
                current_tool_id = None
                current_tool_json_parts = []

        await process.wait()

        # Read stderr if non-zero exit
        stderr_text = ""
        if process.returncode != 0 and process.stderr:
            stderr_bytes = await process.stderr.read()
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            logger.warning(
                "claude process exited %d for session %s: %s",
                process.returncode, session_id, stderr_text,
            )

        # Save the assistant message
        final_content = "".join(full_content_parts).strip()
        if final_content or tool_calls:
            await create_message(
                session_id=session_id,
                role="assistant",
                content=final_content,
                tool_calls=json.dumps(tool_calls) if tool_calls else None,
                thinking="".join(thinking_parts) if thinking_parts else None,
                is_complete=True,
            )
        elif process.returncode != 0:
            # Store the error
            await create_message(
                session_id=session_id,
                role="assistant",
                content=f"[Error] claude exited with code {process.returncode}: {stderr_text}",
                is_complete=True,
            )

        # Mark any remaining running agents as completed
        for tool_id, agent_info in list(running_agents.items()):
            session_broker.publish(session_id, {
                "type": "agent_complete",
                "toolUseId": tool_id,
                "result": "",
                "isError": False,
            })
        running_agents.clear()

        # Publish completion event
        session_broker.publish(session_id, {
            "type": "done",
            "session_id": session_id,
            "exit_code": process.returncode,
        })

        await touch_session(session_id)

    except Exception:
        logger.exception("Error running claude for session %s", session_id)
        session_broker.publish(session_id, {
            "type": "error",
            "session_id": session_id,
            "error": "Internal error running claude subprocess",
        })
    finally:
        _active_processes.pop(session_id, None)
        # Clean up temp image files
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass


async def cancel_session(session_id: str) -> bool:
    """Kill the running subprocess for a session, if any."""
    proc = _active_processes.get(session_id)
    if proc is None:
        return False
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()
    _active_processes.pop(session_id, None)
    session_broker.publish(session_id, {
        "type": "cancelled",
        "session_id": session_id,
    })
    return True
