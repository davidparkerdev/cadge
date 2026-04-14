from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MLX_SERVER_URL = "http://localhost:33339"

_FILLER_WORDS = {
    "a", "an", "the", "me", "my", "i", "we", "you", "your",
    "please", "can", "could", "would", "should", "will",
    "just", "also", "very", "really", "some", "this", "that",
    "it", "its", "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "have", "has", "had", "get", "got",
    "to", "of", "in", "on", "at", "for", "with", "from",
    "and", "or", "but", "so", "if", "then", "how", "what",
    "which", "who", "where", "when", "why",
}


def _get_timestamp() -> str:
    now = datetime.now(timezone.utc).astimezone()
    return now.strftime("%Y-%m-%d %I:%M %p %Z")


def _derive_focus(user_prompt: str) -> str:
    clean = user_prompt.strip()

    about_match = re.search(r'\babout\s+(.+)', clean, re.IGNORECASE)
    if about_match:
        subject = about_match.group(1).strip()
        words = subject.split()[:3]
        return " ".join(words).rstrip(".,!?;:").title()

    words = clean.split()
    meaningful = [w for w in words if w.lower().rstrip(".,!?;:") not in _FILLER_WORDS]
    if not meaningful:
        meaningful = words

    if len(meaningful) <= 3:
        return " ".join(meaningful).rstrip(".,!?;:").title()

    return " ".join(meaningful[-3:]).rstrip(".,!?;:").title()


def _truncate_asked(user_prompt: str) -> str:
    clean = user_prompt.strip()
    if len(clean) > 120:
        return clean[:117] + "..."
    return clean


def _deterministic_done(content: str, tool_calls: list[dict]) -> str:
    if tool_calls:
        tool_names = list(dict.fromkeys(tc.get("name", "unknown") for tc in tool_calls))
        tools_str = ", ".join(tool_names[:5])
        if len(tool_names) > 5:
            tools_str += f" (+{len(tool_names) - 5} more)"
        first_line = ""
        if content:
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("```"):
                    first_line = line[:150]
                    break
        if first_line:
            return f"Used {tools_str}. {first_line}"
        return f"Used {tools_str}"
    elif content:
        clean = content.strip()
        if len(clean) > 200:
            return clean[:197] + "..."
        return clean
    return ""


def _build_structured_summary(
    user_prompt: str,
    content: str,
    tool_calls: list[dict],
    ai_done: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    summary: dict[str, Any] = {
        "time": _get_timestamp(),
        "focus": _derive_focus(user_prompt),
        "asked": _truncate_asked(user_prompt),
        "done": ai_done or _deterministic_done(content, tool_calls),
    }
    if tool_calls:
        tool_names = list(dict.fromkeys(tc.get("name", "unknown") for tc in tool_calls))
        summary["tools"] = tool_names[:8]
    if metadata:
        summary.update(metadata)
    return json.dumps(summary)


def _build_ai_prompt(user_prompt: str, content: str, tool_calls: list[dict]) -> str:
    tool_summary = ""
    if tool_calls:
        tool_names = list(dict.fromkeys(tc.get("name", "unknown") for tc in tool_calls))
        tool_summary = f"\nTools used: {', '.join(tool_names)}"

    response_preview = content[:3000] if content else "(no text response)"

    return (
        f"The user asked:\n\"{user_prompt[:500]}\"\n"
        f"{tool_summary}\n"
        f"The AI responded with:\n{response_preview}\n\n"
        "Write a 1-2 sentence summary of what was done. "
        "Be concise and direct. Do not start with 'The AI' or 'I'. "
        "Just describe the action/result in plain text."
    )


async def _call_anthropic(prompt_text: str, model: str) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt_text}],
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"].strip()
        logger.warning("Anthropic summary API returned status %d", resp.status_code)
    return None


async def _call_mlx_server(prompt_text: str, model: str) -> Optional[str]:
    base_url = os.environ.get("MLX_SERVER_URL", DEFAULT_MLX_SERVER_URL)

    async with httpx.AsyncClient(timeout=15.0) as client:
        payload: dict = {
            "messages": [{"role": "user", "content": prompt_text}],
            "stream": False,
            "max_tokens": 150,
            "temperature": 0.3,
        }
        if model:
            payload["model"] = model

        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
        )
        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    return content.strip()
        logger.warning("MLX server summary API returned status %d", resp.status_code)
    return None


async def generate_summary(
    user_prompt: str,
    content: str,
    tool_calls: Optional[list[dict]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    tool_calls = tool_calls or []

    if not content and not tool_calls:
        return _build_structured_summary(user_prompt, content, tool_calls, metadata=metadata)

    from app.services.settings_store import get_feature_settings
    settings = await get_feature_settings("summary")
    provider_id = settings.get("provider_id", "")
    model = settings.get("model", "")

    if not provider_id:
        return _build_structured_summary(user_prompt, content, tool_calls, metadata=metadata)

    prompt_text = _build_ai_prompt(user_prompt, content, tool_calls)
    ai_done: Optional[str] = None

    try:
        if provider_id == "anthropic":
            ai_done = await _call_anthropic(prompt_text, model or "claude-haiku-4-5-20251001")
        elif provider_id == "mlx-server":
            ai_done = await _call_mlx_server(prompt_text, model)
    except Exception:
        logger.debug("AI summary generation failed, using fallback", exc_info=True)

    return _build_structured_summary(user_prompt, content, tool_calls, ai_done, metadata=metadata)
