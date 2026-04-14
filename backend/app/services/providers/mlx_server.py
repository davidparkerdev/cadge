from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

import httpx

from app.services.event_store import (
    append_event,
    STREAM_START, STREAM_END, STREAM_ERROR, STREAM_CANCELLED,
    CONTENT_DELTA, TOOL_START, TOOL_END, FOCUS_UPDATE, STATS_UPDATE,
)
from app.services.providers.base import BaseProvider, ProviderInfo, ProviderModel
from app.services.providers.mlx_tools import (
    ToolContext,
    execute_tool,
    openai_tool_schemas,
    summarize_tool_call,
)
from app.services.summary_generator import generate_summary
from app.services.session_store import (
    create_message,
    delete_message as _delete_message,
    get_session,
    list_messages,
    touch_session,
    update_message,
)
from app.services.stream_broker import session_broker

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:33339"
DEFAULT_MODEL = "default"
MAX_AGENT_TURNS = 8
STATS_UPDATE_INTERVAL = 0.6

_active_sessions: set[str] = set()
_cancel_flags: dict[str, asyncio.Event] = {}

ROLE_PROMPTS = {
    "product": "You are a product manager. Help define product requirements, write user stories, prioritize features, and think through user experience.",
    "coding": "You are a senior software engineer. Write clean, well-tested code. Follow existing patterns in the codebase. Think through edge cases.",
    "writing": "You are a skilled writer. Help with clear, concise technical writing, documentation, blog posts, and communication.",
    "deep-dive": "You are a deep research analyst. Thoroughly investigate topics and provide comprehensive analysis with evidence.",
    "bug-fixing": "You are a debugging expert. Systematically identify root causes, check logs, trace execution paths, and fix bugs with minimal side effects.",
    "analysis": "You are a data and systems analyst. Analyze patterns, identify bottlenecks, evaluate trade-offs, and provide actionable recommendations.",
    "qa": "You are a QA engineer. Design test cases, find edge cases, verify acceptance criteria, and ensure quality.",
    "frontend": "You are a frontend design engineer specializing in UX and React. Build responsive, accessible, beautiful interfaces with Tailwind CSS.",
    "web-dev": "You are a full-stack web developer. Build robust APIs, responsive UIs, and reliable infrastructure.",
    "game-dev": "You are a game developer. Design game mechanics, implement gameplay systems, optimize performance, and create engaging experiences.",
    "nextjs": "You are a Next.js expert. Build performant server-rendered React applications with app router, server components, and modern patterns.",
}

AGENT_PREAMBLE = (
    "You are an autonomous coding assistant with access to tools (read_file, write_file, "
    "bash, grep, ls, glob). When the user asks you to inspect, modify, or run things, "
    "use the tools. Prefer reading files before making claims. Keep tool calls focused "
    "and narrate briefly between them."
)


def _get_base_url() -> str:
    return os.environ.get("MLX_SERVER_URL", DEFAULT_BASE_URL)


class MLXServerProvider(BaseProvider):

    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id="mlx-server",
            name="MLX Server",
            description="Local Apple Silicon LLMs via the MLX Server (OpenAI-compatible). Supports tools.",
            supports_tools=True,
            supports_thinking=False,
            supports_images=False,
            supports_agents=False,
            requires_api_key=False,
            default_model=DEFAULT_MODEL,
            config={"base_url": _get_base_url()},
        )

    async def list_models(self) -> list[ProviderModel]:
        base_url = _get_base_url()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                models: list[ProviderModel] = []
                for m in data.get("data", []):
                    models.append(ProviderModel(
                        id=m.get("id", "unknown"),
                        name=m.get("id", "unknown"),
                        context_length=m.get("context_length") or m.get("max_context"),
                        owned_by=m.get("owned_by"),
                    ))
                return models
        except httpx.ConnectError:
            logger.warning("MLX server not reachable at %s", base_url)
            return []
        except Exception:
            logger.warning("Failed to list MLX server models", exc_info=True)
            return []

    async def check_status(self) -> dict:
        base_url = _get_base_url()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                data = resp.json()
                return {
                    "status": "available",
                    "base_url": base_url,
                    "model_count": len(data.get("data", [])),
                }
        except httpx.ConnectError:
            return {"status": "unavailable", "detail": f"Cannot connect to {base_url}"}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

    def is_streaming(self, session_id: str) -> bool:
        return session_id in _active_sessions

    def active_count(self) -> int:
        return len(_active_sessions)

    def cleanup_session(self, session_id: str) -> None:
        _active_sessions.discard(session_id)
        _cancel_flags.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        if session_id not in _active_sessions:
            return False
        cancel_event = _cancel_flags.get(session_id)
        if cancel_event:
            cancel_event.set()
        session_broker.publish(session_id, {"type": "cancelled", "session_id": session_id})
        await append_event(session_id, STREAM_CANCELLED, {})
        return True

    async def send_message(
        self,
        session_id: str,
        prompt: str,
        images: Optional[list[str]] = None,
    ) -> None:
        if session_id in _active_sessions:
            await self.cancel(session_id)
            await asyncio.sleep(0.1)

        cancel_event = asyncio.Event()
        _cancel_flags[session_id] = cancel_event
        _active_sessions.add(session_id)

        try:
            await self._run_agent_loop(session_id, prompt, cancel_event)
        finally:
            _active_sessions.discard(session_id)
            _cancel_flags.pop(session_id, None)

    async def _run_agent_loop(
        self,
        session_id: str,
        prompt: str,
        cancel_event: asyncio.Event,
    ) -> None:
        session = await get_session(session_id)
        if not session:
            logger.error("send_message called for unknown session %s", session_id)
            return

        start_mono = time.monotonic()
        role = session.get("role")
        model = session.get("model") or DEFAULT_MODEL
        project_dir = session.get("project_dir")
        tool_ctx = ToolContext(project_dir=project_dir)

        system_parts: list[str] = [AGENT_PREAMBLE]
        if role and role in ROLE_PROMPTS:
            system_parts.append(ROLE_PROMPTS[role])

        messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]
        previous = await list_messages(session_id, limit=100)
        for msg in previous:
            if msg["role"] in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        session_broker.publish(session_id, {"type": "start", "session_id": session_id})
        placeholder = await create_message(
            session_id=session_id, role="assistant", content="",
            is_complete=False, status="streaming",
        )
        assistant_msg_id = placeholder["id"]
        await append_event(session_id, STREAM_START, {"message_id": assistant_msg_id})
        await self._emit_focus(session_id, "Thinking", kind="thinking")

        assembled_content: list[str] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        last_error: Optional[str] = None

        try:
            for turn in range(MAX_AGENT_TURNS):
                if cancel_event.is_set():
                    break

                result = await self._run_one_turn(
                    session_id=session_id,
                    model=model,
                    messages=messages,
                    cancel_event=cancel_event,
                    tool_ctx=tool_ctx,
                    start_mono=start_mono,
                    prior_completion_tokens=total_completion_tokens,
                )

                if result.get("error"):
                    last_error = result["error"]
                    break

                content = result.get("content") or ""
                tool_calls = result.get("tool_calls") or []
                usage = result.get("usage") or {}

                if usage:
                    total_prompt_tokens = usage.get("prompt_tokens", total_prompt_tokens)
                    total_completion_tokens += usage.get("completion_tokens", 0)

                if content:
                    assembled_content.append(content)

                if not tool_calls:
                    break

                assistant_msg = {"role": "assistant"}
                if content:
                    assistant_msg["content"] = content
                else:
                    assistant_msg["content"] = None
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc.get("arguments_json") or "{}",
                        },
                    }
                    for tc in tool_calls
                ]
                messages.append(assistant_msg)

                for tc in tool_calls:
                    if cancel_event.is_set():
                        break
                    tool_output = await self._run_tool(session_id, tc, tool_ctx)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_output)[:50_000],
                    })

            if cancel_event.is_set():
                partial = "".join(assembled_content).strip()
                await update_message(
                    assistant_msg_id,
                    content=partial or "[Cancelled]",
                    is_complete=True, status="incomplete",
                )
                return

            final_content = "".join(assembled_content).strip()
            duration_seconds = round(time.monotonic() - start_mono, 1)

            await self._emit_stats(
                session_id,
                elapsed=duration_seconds,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                model=model,
                final=True,
            )
            await self._emit_focus(session_id, "Done", kind="idle")

            if last_error:
                err_msg = f"[Error] {last_error}"
                await update_message(
                    assistant_msg_id,
                    content=(final_content + "\n\n" + err_msg) if final_content else err_msg,
                    is_complete=True, status="error",
                )
                await append_event(session_id, STREAM_ERROR, {"error": last_error})
                session_broker.publish(session_id, {
                    "type": "error", "session_id": session_id, "error": last_error,
                })
                return

            if final_content:
                summary_metadata = {
                    "model": model if model != "default" else None,
                    "duration_s": duration_seconds,
                    "tokens_in": total_prompt_tokens or None,
                    "tokens_out": total_completion_tokens or None,
                }
                summary = await generate_summary(prompt, final_content, metadata=summary_metadata)
                await update_message(
                    assistant_msg_id,
                    content=final_content,
                    is_complete=True, status="complete", summary=summary,
                )
            else:
                summary = None
                await _delete_message(assistant_msg_id)

            session_broker.publish(session_id, {
                "type": "done", "session_id": session_id, "exit_code": 0,
            })
            await append_event(session_id, STREAM_END, {
                "message_id": assistant_msg_id, "exit_code": 0, "summary": summary,
            })
            await touch_session(session_id)

        except httpx.ConnectError:
            error_msg = f"Cannot connect to MLX Server at {_get_base_url()}. Is it running?"
            logger.error(error_msg)
            await append_event(session_id, STREAM_ERROR, {"error": error_msg})
            await update_message(
                assistant_msg_id,
                content=f"[Error] {error_msg}",
                is_complete=True, status="error",
            )
            session_broker.publish(session_id, {
                "type": "error", "session_id": session_id, "error": error_msg,
            })
        except Exception as exc:
            logger.exception("Error in MLX agent loop for session %s", session_id)
            await append_event(session_id, STREAM_ERROR, {"error": str(exc)})
            partial = "".join(assembled_content).strip()
            await update_message(
                assistant_msg_id,
                content=partial or f"[Error] {exc}",
                is_complete=True, status="error",
            )
            session_broker.publish(session_id, {
                "type": "error", "session_id": session_id, "error": str(exc),
            })

    async def _run_one_turn(
        self,
        *,
        session_id: str,
        model: str,
        messages: list[dict],
        cancel_event: asyncio.Event,
        tool_ctx: ToolContext,
        start_mono: float,
        prior_completion_tokens: int,
    ) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "tools": openai_tool_schemas(),
        }

        base_url = _get_base_url()
        content_parts: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        usage: dict = {}
        turn_tokens = 0
        last_stats_emit = 0.0
        first_token = False

        timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{base_url}/v1/chat/completions", json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    return {"error": f"MLX server error {response.status_code}: {body.decode(errors='replace')[:500]}"}

                async for line in response.aiter_lines():
                    if cancel_event.is_set():
                        return {"error": None, "content": "".join(content_parts), "tool_calls": [], "usage": usage}
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if "error" in chunk:
                        return {"error": str(chunk["error"])}

                    choices = chunk.get("choices") or []
                    if not choices:
                        if "usage" in chunk:
                            usage = chunk["usage"]
                        continue

                    delta = choices[0].get("delta") or {}
                    content_piece = delta.get("content")
                    if content_piece:
                        if not first_token:
                            first_token = True
                            await self._emit_focus(session_id, "Responding", kind="response")
                        content_parts.append(content_piece)
                        turn_tokens += 1
                        session_broker.publish(session_id, {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": content_piece},
                        })
                        await append_event(session_id, CONTENT_DELTA, {"text": content_piece})

                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        existing = tool_calls_by_index.setdefault(
                            idx, {"id": "", "name": "", "arguments_json": ""}
                        )
                        if tc.get("id"):
                            existing["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            existing["name"] = fn["name"]
                        if fn.get("arguments") is not None:
                            args_piece = fn["arguments"]
                            if isinstance(args_piece, str):
                                existing["arguments_json"] += args_piece
                            else:
                                existing["arguments_json"] = json.dumps(args_piece)

                    if "usage" in chunk:
                        usage = chunk["usage"]

                    finish_reason = choices[0].get("finish_reason")
                    if finish_reason:
                        break

                    now = time.monotonic()
                    if now - last_stats_emit >= STATS_UPDATE_INTERVAL:
                        last_stats_emit = now
                        elapsed = now - start_mono
                        completed = prior_completion_tokens + turn_tokens
                        tps = completed / elapsed if elapsed > 0 else 0.0
                        await self._emit_stats(
                            session_id,
                            elapsed=elapsed,
                            prompt_tokens=usage.get("prompt_tokens"),
                            completion_tokens=completed,
                            tokens_per_second=tps,
                            model=model,
                        )

        tool_calls = []
        for idx in sorted(tool_calls_by_index.keys()):
            tc = tool_calls_by_index[idx]
            if not tc.get("name"):
                continue
            if not tc.get("id"):
                tc["id"] = f"call_{uuid.uuid4().hex[:12]}"
            tool_calls.append(tc)

        return {
            "content": "".join(content_parts),
            "tool_calls": tool_calls,
            "usage": usage,
        }

    async def _run_tool(self, session_id: str, tc: dict, tool_ctx: ToolContext) -> dict:
        name = tc["name"]
        raw_args = tc.get("arguments_json") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            if not isinstance(args, dict):
                args = {"value": args}
        except json.JSONDecodeError:
            args = {}

        summary = summarize_tool_call(name, args)
        await self._emit_focus(session_id, summary, kind="tool", detail=name)
        await append_event(session_id, TOOL_START, {
            "tool_id": tc["id"],
            "tool_name": name,
            "tool_input": args,
        })
        session_broker.publish(session_id, {
            "type": "tool_start", "tool_id": tc["id"], "tool_name": name,
        })

        try:
            result = await execute_tool(name, args, tool_ctx)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            result = {"error": f"Tool execution failed: {exc}"}

        try:
            result_str = json.dumps(result)
        except (TypeError, ValueError):
            result_str = str(result)
        if len(result_str) > 20_000:
            preview = result_str[:20_000] + "...[truncated]"
        else:
            preview = result_str

        await append_event(session_id, TOOL_END, {
            "tool_id": tc["id"],
            "tool_name": name,
            "output": preview,
            "is_error": isinstance(result, dict) and "error" in result,
        })
        session_broker.publish(session_id, {
            "type": "tool_end", "tool_id": tc["id"], "tool_name": name,
        })
        return result

    async def _emit_focus(
        self,
        session_id: str,
        summary: str,
        *,
        kind: str = "thinking",
        detail: Optional[str] = None,
    ) -> None:
        data = {"summary": summary, "kind": kind, "updated_at": time.time()}
        if detail:
            data["detail"] = detail
        await append_event(session_id, FOCUS_UPDATE, data)
        session_broker.publish(session_id, {"type": "focus_update", "data": data})

    async def _emit_stats(
        self,
        session_id: str,
        *,
        elapsed: float,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        tokens_per_second: Optional[float] = None,
        model: Optional[str] = None,
        final: bool = False,
    ) -> None:
        data: dict = {"elapsed_seconds": round(elapsed, 2), "final": final}
        if prompt_tokens is not None:
            data["tokens_in"] = prompt_tokens
        if completion_tokens is not None:
            data["tokens_out"] = completion_tokens
        if tokens_per_second is not None:
            data["tokens_per_second"] = round(tokens_per_second, 2)
        if model is not None:
            data["model"] = model
        if prompt_tokens is not None and completion_tokens is not None:
            data["context_used"] = prompt_tokens + completion_tokens
        await append_event(session_id, STATS_UPDATE, data)
        session_broker.publish(session_id, {"type": "stats_update", "data": data})
