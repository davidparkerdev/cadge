from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import tempfile
import time
from typing import Optional

from app.services.event_store import (
    append_event,
    STREAM_START, STREAM_END, STREAM_ERROR, STREAM_CANCELLED,
    CONTENT_DELTA, THINKING_DELTA,
    TOOL_START, TOOL_END,
    AGENT_SPAWN, AGENT_COMPLETE,
)
from app.services.observatory_client import push_session_event
from app.services.summary_generator import generate_summary
from app.services.providers.base import BaseProvider, ProviderInfo, ProviderModel
from app.services.session_store import (
    create_message,
    delete_message as _delete_message,
    get_session,
    mark_provider_initialized,
    touch_session,
    update_message,
)
from app.services.stream_broker import session_broker

logger = logging.getLogger(__name__)

_active_processes: dict[str, Optional[asyncio.subprocess.Process]] = {}
_session_locks: dict[str, asyncio.Lock] = {}

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.environ.get("CADGE_PROJECT_ROOT", os.path.dirname(_BACKEND_DIR))

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


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


async def _kill_stale_claude_processes(claude_session_id: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-f", claude_session_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0 and stdout:
            pids = [p.strip() for p in stdout.decode().strip().split("\n") if p.strip()]
            killed_any = False
            for pid_str in pids:
                try:
                    pid = int(pid_str)
                    if pid == os.getpid():
                        continue
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Killed stale claude process %d for session %s", pid, claude_session_id)
                    killed_any = True
                except (ValueError, ProcessLookupError, PermissionError):
                    pass
            if killed_any:
                await asyncio.sleep(1.5)
                return True
    except Exception:
        logger.debug("Failed to check for stale processes", exc_info=True)
    return False


class ClaudeCodeProvider(BaseProvider):

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id="claude-code",
            name="Claude Code",
            description="Claude Code CLI sessions with full tool use, thinking, and agent capabilities",
            supports_tools=True,
            supports_thinking=True,
            supports_images=True,
            supports_agents=True,
            requires_api_key=False,
            default_model="claude-sonnet-4-20250514",
        )

    async def list_models(self) -> list[ProviderModel]:
        return [
            ProviderModel(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", context_length=200000, owned_by="anthropic"),
            ProviderModel(id="claude-opus-4-20250514", name="Claude Opus 4", context_length=200000, owned_by="anthropic"),
            ProviderModel(id="claude-haiku-4-20250514", name="Claude Haiku 4", context_length=200000, owned_by="anthropic"),
        ]

    async def check_status(self) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            if proc.returncode == 0:
                return {"status": "available", "version": stdout.decode().strip()}
            return {"status": "error", "detail": "claude CLI returned non-zero"}
        except FileNotFoundError:
            return {"status": "unavailable", "detail": "claude CLI not found in PATH"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    def is_streaming(self, session_id: str) -> bool:
        return session_id in _active_processes

    def active_count(self) -> int:
        return len(_active_processes)

    def cleanup_session(self, session_id: str) -> None:
        _session_locks.pop(session_id, None)
        _active_processes.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        if session_id not in _active_processes:
            return False
        proc = _active_processes.get(session_id)
        if proc is None:
            _active_processes.pop(session_id, None)
            return True
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
        _active_processes.pop(session_id, None)
        session_broker.publish(session_id, {"type": "cancelled", "session_id": session_id})
        await append_event(session_id, STREAM_CANCELLED, {})
        push_session_event(session_id=session_id, event_type="cancel", error="Cancelled by user")
        return True

    async def send_message(
        self,
        session_id: str,
        prompt: str,
        images: Optional[list[str]] = None,
    ) -> None:
        lock = _get_session_lock(session_id)
        if session_id in _active_processes:
            logger.info("Cancelling active process for session %s before sending new message", session_id)
            await self.cancel(session_id)
        async with lock:
            await self._run_claude(session_id, prompt, images)

    async def _run_claude(
        self,
        session_id: str,
        prompt: str,
        images: Optional[list[str]] = None,
        _retry_count: int = 0,
    ) -> None:
        session = await get_session(session_id)
        if not session:
            logger.error("send_message called for unknown session %s", session_id)
            return

        provider_session_id = session.get("provider_session_id") or session.get("claude_session_id")

        await _kill_stale_claude_processes(provider_session_id)
        role = session.get("role")
        project_dir = session.get("project_dir")
        project_name = session.get("project_name")

        push_session_event(
            session_id=session_id,
            event_type="start",
            title=session.get("title", ""),
            role=role,
            project_name=project_name,
            project_dir=project_dir,
        )

        _start_mono = time.monotonic()
        _input_tokens: int = 0
        _output_tokens: int = 0
        original_prompt = prompt

        is_first_message = not session.get("provider_initialized", False) and not session.get("claude_initialized", False)

        if role and role in ROLE_PROMPTS and is_first_message:
            prompt = f"{ROLE_PROMPTS[role]}\n\n{prompt}"

        abs_project_dir: str | None = None
        if project_dir:
            if os.path.isabs(project_dir):
                abs_project_dir = project_dir
            else:
                abs_project_dir = os.path.join(PROJECT_ROOT, project_dir)
            if not os.path.isdir(abs_project_dir):
                logger.warning("project_dir %s does not exist, ignoring", abs_project_dir)
                abs_project_dir = None

        temp_files: list[str] = []
        add_dirs: list[str] = []
        process: Optional[asyncio.subprocess.Process] = None
        assistant_msg_id: Optional[str] = None
        full_content_parts: list[str] = []
        tool_calls: list[dict] = []
        thinking_parts: list[str] = []
        stderr_task: Optional[asyncio.Task] = None
        _model: str = ""

        try:
            _active_processes[session_id] = None

            session_broker.publish(session_id, {"type": "start", "session_id": session_id})

            placeholder = await create_message(
                session_id=session_id, role="assistant", content="",
                is_complete=False, status="streaming",
            )
            assistant_msg_id = placeholder["id"]
            await append_event(session_id, STREAM_START, {"message_id": assistant_msg_id})

            if images:
                image_paths: list[str] = []
                for i, b64 in enumerate(images):
                    try:
                        raw_b64 = b64.split(",", 1)[-1] if "," in b64 else b64
                        data = base64.b64decode(raw_b64)
                        mime_type = 'image/png'
                        if ',' in b64 and ':' in b64:
                            try:
                                mime_type = b64.split(';', 1)[0].split(':', 1)[1]
                            except (IndexError, ValueError):
                                pass
                        _EXT_MAP = {
                            'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
                            'image/webp': '.webp', 'image/heic': '.heic', 'image/heif': '.heif',
                        }
                        suffix = _EXT_MAP.get(mime_type, '.png')
                        fd, path = tempfile.mkstemp(suffix=suffix, prefix=f"nexus_img_{i}_")
                        os.write(fd, data)
                        os.close(fd)
                        temp_files.append(path)
                        image_paths.append(path)
                    except Exception:
                        logger.exception("Failed to decode image %d", i)

                if image_paths:
                    add_dirs.append(os.path.dirname(image_paths[0]))
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

            if session_id not in _active_processes:
                logger.info("Session %s was cancelled during image processing, aborting", session_id)
                if assistant_msg_id:
                    await _delete_message(assistant_msg_id)
                return

            cmd = ["claude", "-p", prompt]
            if is_first_message:
                cmd.extend(["--session-id", provider_session_id])
            else:
                cmd.extend(["--resume", provider_session_id])
            cmd.extend([
                "--output-format", "stream-json",
                "--verbose",
                "--dangerously-skip-permissions",
            ])
            for d in add_dirs:
                cmd.extend(["--add-dir", d])

            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            PERIODIC_SAVE_INTERVAL = 5.0

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
                cwd=abs_project_dir,
                limit=10 * 1024 * 1024,
            )
            _active_processes[session_id] = process

            current_tool_name: str | None = None
            current_tool_id: str | None = None
            current_tool_json_parts: list[str] = []
            running_agents: dict[str, dict] = {}

            stderr_parts: list[bytes] = []

            async def _drain_stderr():
                assert process.stderr is not None
                while True:
                    chunk = await process.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_parts.append(chunk)

            stderr_task = asyncio.create_task(_drain_stderr())

            last_save_time = time.monotonic()
            last_saved_content_len = 0

            assert process.stdout is not None
            while True:
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=300.0)
                except asyncio.TimeoutError:
                    logger.error("claude process stalled (no output for 5 min) for session %s", session_id)
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning("claude process did not exit within 5s after SIGKILL for session %s", session_id)
                    break
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    event = {"type": "raw", "text": text}

                session_broker.publish(session_id, event)

                event_type = event.get("type", "")
                if event_type == "assistant":
                    content = event.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    t = block.get("text", "")
                                    if t and not full_content_parts:
                                        full_content_parts.append(t)
                                        await append_event(session_id, CONTENT_DELTA, {"text": t})
                                elif block.get("type") == "tool_use":
                                    tool_calls.append(block)
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
                                            "type": "agent_complete", "toolUseId": tool_use_id,
                                            "result": result_text[:500], "isError": block.get("is_error", False),
                                        })
                                        await append_event(session_id, AGENT_COMPLETE, {
                                            "tool_use_id": tool_use_id,
                                            "result": result_text[:500],
                                            "is_error": block.get("is_error", False),
                                        })
                                        running_agents.pop(tool_use_id, None)
                elif event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        full_content_parts.append(delta.get("text", ""))
                        await append_event(session_id, CONTENT_DELTA, {"text": delta.get("text", "")})
                    elif delta.get("type") == "thinking_delta":
                        thinking_parts.append(delta.get("thinking", ""))
                        await append_event(session_id, THINKING_DELTA, {"text": delta.get("thinking", "")})
                    elif delta.get("type") == "input_json_delta":
                        if delta.get("partial_json"):
                            current_tool_json_parts.append(delta["partial_json"])
                            total_size = sum(len(p) for p in current_tool_json_parts)
                            if total_size > 10 * 1024 * 1024:
                                logger.warning("Tool JSON accumulator exceeded 10MB for session %s, clearing", session_id)
                                current_tool_json_parts = []
                elif event_type == "result":
                    result_text = event.get("result", "")
                    if result_text and not full_content_parts:
                        full_content_parts.append(result_text)
                    usage = event.get("usage") or event.get("usage_data") or {}
                    if usage:
                        _input_tokens += usage.get("input_tokens", 0)
                        _output_tokens += usage.get("output_tokens", 0)
                elif event_type == "message_delta":
                    usage = event.get("usage") or {}
                    if usage:
                        _output_tokens = max(_output_tokens, usage.get("output_tokens", 0))
                elif event_type == "message_start":
                    msg = event.get("message", {})
                    if msg.get("model"):
                        _model = msg["model"]
                    usage = msg.get("usage") or {}
                    if usage:
                        _input_tokens = max(_input_tokens, usage.get("input_tokens", 0))
                elif event_type == "content_block_start":
                    cb = event.get("content_block", {})
                    if cb.get("type") == "tool_use":
                        current_tool_name = cb.get("name")
                        current_tool_id = cb.get("id")
                        current_tool_json_parts = []
                        await append_event(session_id, TOOL_START, {
                            "tool_name": cb.get("name"), "tool_id": cb.get("id"),
                        })
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
                        session_broker.publish(session_id, {"type": "agent_spawn", **agent_info})
                        await append_event(session_id, AGENT_SPAWN, {
                            "tool_use_id": current_tool_id,
                            "description": tool_input.get("description", "Sub-agent task"),
                            "subagent_type": tool_input.get("subagent_type", "Task"),
                        })
                    elif current_tool_name and current_tool_id:
                        await append_event(session_id, TOOL_END, {
                            "tool_name": current_tool_name, "tool_id": current_tool_id, "status": "completed",
                        })
                    current_tool_name = None
                    current_tool_id = None
                    current_tool_json_parts = []

                now_mono = time.monotonic()
                current_content_len = len(full_content_parts)
                if (
                    now_mono - last_save_time >= PERIODIC_SAVE_INTERVAL
                    and current_content_len > last_saved_content_len
                    and assistant_msg_id
                ):
                    try:
                        partial_content = "".join(full_content_parts).strip()
                        await update_message(
                            assistant_msg_id,
                            content=partial_content,
                            thinking="".join(thinking_parts) if thinking_parts else None,
                            tool_calls=json.dumps(tool_calls) if tool_calls else None,
                        )
                        last_save_time = now_mono
                        last_saved_content_len = current_content_len
                    except Exception:
                        logger.warning("Failed periodic save for message %s", assistant_msg_id, exc_info=True)

            await process.wait()
            await stderr_task
            stderr_text = b"".join(stderr_parts).decode("utf-8", errors="replace").strip()
            if process.returncode != 0 and stderr_text:
                logger.warning("claude process exited %d for session %s: %s", process.returncode, session_id, stderr_text)

            if (
                process.returncode != 0
                and "already in use" in stderr_text
                and _retry_count < 1
            ):
                logger.info("Session %s still in use, retrying after cleanup (attempt %d)", session_id, _retry_count + 1)
                if assistant_msg_id:
                    await _delete_message(assistant_msg_id)
                await _kill_stale_claude_processes(provider_session_id)
                await self._run_claude(session_id, prompt, images, _retry_count=_retry_count + 1)
                return

            if is_first_message:
                await mark_provider_initialized(session_id)

            final_content = "".join(full_content_parts).strip()

            _PRICING = {
                "opus": (15.0, 75.0),
                "sonnet": (3.0, 15.0),
                "haiku": (0.25, 1.25),
            }
            tier = "sonnet"
            model_lower = _model.lower()
            for key in _PRICING:
                if key in model_lower:
                    tier = key
                    break
            input_rate, output_rate = _PRICING[tier]
            cost_usd = (_input_tokens * input_rate / 1_000_000) + (_output_tokens * output_rate / 1_000_000)
            duration_seconds = round(time.monotonic() - _start_mono, 1)

            summary_metadata = {
                "model": _model or None,
                "input_tokens": _input_tokens or None,
                "output_tokens": _output_tokens or None,
                "duration_s": duration_seconds,
                "cost_usd": round(cost_usd, 4) if cost_usd > 0 else None,
            }
            total_tokens = _input_tokens + _output_tokens
            if duration_seconds > 0 and total_tokens > 0:
                summary_metadata["tok_per_s"] = round(total_tokens / duration_seconds, 1)

            summary = await generate_summary(original_prompt, final_content, tool_calls, metadata=summary_metadata)
            if final_content or tool_calls:
                await update_message(
                    assistant_msg_id,
                    content=final_content,
                    tool_calls=json.dumps(tool_calls) if tool_calls else None,
                    thinking="".join(thinking_parts) if thinking_parts else None,
                    is_complete=True, status="complete", summary=summary,
                )
            elif process.returncode != 0:
                await update_message(
                    assistant_msg_id,
                    content=f"[Error] claude exited with code {process.returncode}: {stderr_text}",
                    is_complete=True, status="error",
                )
            else:
                await _delete_message(assistant_msg_id)

            for tool_id, agent_info in list(running_agents.items()):
                session_broker.publish(session_id, {
                    "type": "agent_complete", "toolUseId": tool_id, "result": "", "isError": False,
                })
            running_agents.clear()

            session_broker.publish(session_id, {
                "type": "done", "session_id": session_id, "exit_code": process.returncode,
            })
            await append_event(session_id, STREAM_END, {
                "message_id": assistant_msg_id, "exit_code": process.returncode, "summary": summary,
            })
            await touch_session(session_id)

            push_session_event(
                session_id=session_id, event_type="complete",
                exit_code=process.returncode if process else -1,
                input_tokens=_input_tokens, output_tokens=_output_tokens,
                cost_usd=cost_usd, duration_seconds=duration_seconds,
            )

        except Exception as exc:
            logger.exception("Error running claude for session %s", session_id)
            await append_event(session_id, STREAM_ERROR, {"error": str(exc)})
            push_session_event(
                session_id=session_id, event_type="failure",
                error=str(exc), duration_seconds=round(time.monotonic() - _start_mono, 1),
            )
            if assistant_msg_id:
                try:
                    partial_content = "".join(full_content_parts).strip()
                    await update_message(
                        assistant_msg_id,
                        content=partial_content or "[Error] Stream interrupted unexpectedly",
                        thinking="".join(thinking_parts) if thinking_parts else None,
                        tool_calls=json.dumps(tool_calls) if tool_calls else None,
                        is_complete=True, status="error",
                    )
                except Exception:
                    logger.warning("Failed to save error state for message %s", assistant_msg_id, exc_info=True)
            session_broker.publish(session_id, {
                "type": "error", "session_id": session_id, "error": "Internal error running claude subprocess",
            })
            if is_first_message and process is not None:
                try:
                    await mark_provider_initialized(session_id)
                except Exception:
                    logger.warning("Failed to mark session initialized after error", exc_info=True)
        finally:
            _active_processes.pop(session_id, None)
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except (asyncio.CancelledError, Exception):
                    pass
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass
