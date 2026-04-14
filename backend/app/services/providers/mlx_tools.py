from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 512_000
MAX_GREP_MATCHES = 200
MAX_GLOB_RESULTS = 500
MAX_BASH_OUTPUT = 100_000
BASH_TIMEOUT_SECONDS = 60


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, "ToolContext"], Any]


@dataclass
class ToolContext:
    project_dir: Optional[str]

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        base = Path(self.project_dir) if self.project_dir else Path.cwd()
        return (base / p).resolve()


def _read_file(args: dict, ctx: ToolContext) -> dict:
    path = args.get("path")
    if not path:
        return {"error": "path is required"}
    target = ctx.resolve(path)
    if not target.exists():
        return {"error": f"File not found: {target}"}
    if not target.is_file():
        return {"error": f"Not a file: {target}"}
    try:
        data = target.read_bytes()
    except Exception as exc:
        return {"error": f"Read failed: {exc}"}
    truncated = False
    if len(data) > MAX_FILE_BYTES:
        data = data[:MAX_FILE_BYTES]
        truncated = True
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"error": "File is not utf-8 text"}
    result = {"path": str(target), "content": text, "bytes": len(data)}
    if truncated:
        result["truncated"] = True
        result["note"] = f"Output truncated at {MAX_FILE_BYTES} bytes"
    return result


def _write_file(args: dict, ctx: ToolContext) -> dict:
    path = args.get("path")
    content = args.get("content", "")
    if not path:
        return {"error": "path is required"}
    target = ctx.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
    except Exception as exc:
        return {"error": f"Write failed: {exc}"}
    return {"path": str(target), "bytes": len(content.encode("utf-8")), "ok": True}


def _bash(args: dict, ctx: ToolContext) -> dict:
    command = args.get("command")
    if not command:
        return {"error": "command is required"}
    cwd = ctx.project_dir if ctx.project_dir and os.path.isdir(ctx.project_dir) else None
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            timeout=BASH_TIMEOUT_SECONDS,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {BASH_TIMEOUT_SECONDS}s", "command": command}
    except Exception as exc:
        return {"error": f"Command failed: {exc}", "command": command}
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    truncated = False
    if len(stdout) > MAX_BASH_OUTPUT:
        stdout = stdout[:MAX_BASH_OUTPUT]
        truncated = True
    if len(stderr) > MAX_BASH_OUTPUT:
        stderr = stderr[:MAX_BASH_OUTPUT]
        truncated = True
    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": truncated,
        "cwd": cwd or os.getcwd(),
    }


def _grep(args: dict, ctx: ToolContext) -> dict:
    pattern = args.get("pattern")
    if not pattern:
        return {"error": "pattern is required"}
    path = args.get("path") or ctx.project_dir or "."
    glob = args.get("glob")
    base = ctx.resolve(path)
    if not base.exists():
        return {"error": f"Path not found: {base}"}
    rg_cmd = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-count", "5"]
    if glob:
        rg_cmd.extend(["--glob", glob])
    rg_cmd.extend(["-e", pattern, str(base)])

    grep_cmd = ["grep", "-rn", "-E", "--color=never", "--max-count=5"]
    if glob:
        grep_cmd.extend(["--include", glob])
    grep_cmd.extend(["-e", pattern, str(base)])

    try:
        try:
            proc = subprocess.run(rg_cmd, capture_output=True, timeout=30, text=True)
        except FileNotFoundError:
            proc = subprocess.run(grep_cmd, capture_output=True, timeout=30, text=True)
    except FileNotFoundError:
        return {"error": "neither ripgrep (rg) nor grep is available"}
    except subprocess.TimeoutExpired:
        return {"error": "grep timed out after 30s"}
    lines = (proc.stdout or "").splitlines()
    truncated = False
    if len(lines) > MAX_GREP_MATCHES:
        lines = lines[:MAX_GREP_MATCHES]
        truncated = True
    return {
        "pattern": pattern,
        "path": str(base),
        "match_count": len(lines),
        "matches": lines,
        "truncated": truncated,
    }


def _ls(args: dict, ctx: ToolContext) -> dict:
    path = args.get("path") or ctx.project_dir or "."
    target = ctx.resolve(path)
    if not target.exists():
        return {"error": f"Path not found: {target}"}
    if not target.is_dir():
        return {"error": f"Not a directory: {target}"}
    entries = []
    try:
        for child in sorted(target.iterdir()):
            if child.name.startswith("."):
                continue
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            })
    except Exception as exc:
        return {"error": f"ls failed: {exc}"}
    return {"path": str(target), "entries": entries}


def _glob(args: dict, ctx: ToolContext) -> dict:
    pattern = args.get("pattern")
    if not pattern:
        return {"error": "pattern is required"}
    path = args.get("path") or ctx.project_dir or "."
    base = ctx.resolve(path)
    if not base.exists():
        return {"error": f"Path not found: {base}"}
    matches = []
    try:
        for p in sorted(base.glob(pattern)):
            matches.append(str(p))
            if len(matches) >= MAX_GLOB_RESULTS:
                break
    except Exception as exc:
        return {"error": f"glob failed: {exc}"}
    return {"pattern": pattern, "root": str(base), "count": len(matches), "matches": matches}


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="read_file",
        description="Read a file from the project (or absolute path). Returns utf-8 text, truncated at 512KB.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative (to project_dir) or absolute path"},
            },
            "required": ["path"],
        },
        handler=_read_file,
    ),
    ToolSpec(
        name="write_file",
        description="Write utf-8 text to a file. Creates parent directories. Overwrites if the file exists.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative or absolute path"},
                "content": {"type": "string", "description": "File contents to write"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    ),
    ToolSpec(
        name="bash",
        description="Run a shell command in the project directory. Has a 60s timeout. Output truncated at 100KB.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
            },
            "required": ["command"],
        },
        handler=_bash,
    ),
    ToolSpec(
        name="grep",
        description="Search file contents with ripgrep. Returns matching lines with file:line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex or literal to search for"},
                "path": {"type": "string", "description": "Directory or file to search (default: project_dir)"},
                "glob": {"type": "string", "description": "File glob filter, e.g. '*.py'"},
            },
            "required": ["pattern"],
        },
        handler=_grep,
    ),
    ToolSpec(
        name="ls",
        description="List non-hidden entries in a directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: project_dir)"},
            },
        },
        handler=_ls,
    ),
    ToolSpec(
        name="glob",
        description="Find files by glob pattern (e.g. '**/*.py').",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern"},
                "path": {"type": "string", "description": "Root directory (default: project_dir)"},
            },
            "required": ["pattern"],
        },
        handler=_glob,
    ),
]

_TOOL_MAP = {spec.name: spec for spec in TOOL_SPECS}


def openai_tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in TOOL_SPECS
    ]


async def execute_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    spec = _TOOL_MAP.get(name)
    if not spec:
        return {"error": f"Unknown tool: {name}"}
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, spec.handler, args or {}, ctx)


def summarize_tool_call(name: str, args: dict) -> str:
    if name == "read_file":
        return f"Reading {args.get('path', '?')}"
    if name == "write_file":
        return f"Writing {args.get('path', '?')}"
    if name == "bash":
        cmd = args.get("command", "")
        short = cmd if len(cmd) <= 60 else cmd[:57] + "..."
        return f"$ {short}"
    if name == "grep":
        return f"Searching for {args.get('pattern', '?')!r}"
    if name == "ls":
        return f"Listing {args.get('path', '.')}"
    if name == "glob":
        return f"Globbing {args.get('pattern', '?')}"
    return f"{name}({', '.join(f'{k}=...' for k in args)})"
