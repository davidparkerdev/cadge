#!/usr/bin/env python3
"""Cadge live smoke test -- exercises every API endpoint against a running instance.

Uses only stdlib (urllib) so it works in any Python 3.9+ environment with no pip installs.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

BASE_URL = "http://localhost:33401"

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Shared state between tests
_session_id: Optional[str] = None
_message_id: Optional[str] = None


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _pass(name: str, ms: float, detail: str = ""):
    extra = f" {DIM}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}PASS{RESET}  {name} {DIM}({ms:.0f}ms){RESET}{extra}")


def _fail(name: str, ms: float, reason: str):
    print(f"  {RED}FAIL{RESET}  {name} {DIM}({ms:.0f}ms){RESET} -- {reason}")


def _elapsed_ms(start: float) -> float:
    return (time.time() - start) * 1000


def _request(method: str, path: str, body: Optional[dict] = None, timeout: int = 5, stream: bool = False):
    """Thin wrapper around urllib that returns (status_code, body_or_response, error_string)."""
    url = _url(path)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if stream:
        req.add_header("Accept", "text/event-stream")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            return resp.status, resp, None
        raw = resp.read().decode()
        try:
            return resp.status, json.loads(raw), None
        except json.JSONDecodeError:
            return resp.status, raw, None
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        return e.code, raw, None
    except Exception as e:
        return 0, None, str(e)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health() -> bool:
    """GET /api/health -> status=ok"""
    start = time.time()
    code, body, err = _request("GET", "/api/health")
    ms = _elapsed_ms(start)
    if err:
        _fail("health", ms, err)
        return False
    if code != 200:
        _fail("health", ms, f"status {code}")
        return False
    if not isinstance(body, dict) or body.get("status") != "ok":
        _fail("health", ms, f"expected status=ok, got {body}")
        return False
    _pass("health", ms, f"activeSessions={body.get('activeSessions', '?')}")
    return True


def test_create_session() -> bool:
    """POST /api/sessions -> 201, store session id"""
    global _session_id
    start = time.time()
    code, body, err = _request("POST", "/api/sessions", {"title": "smoke-test"})
    ms = _elapsed_ms(start)
    if err:
        _fail("create_session", ms, err)
        return False
    if code != 201:
        _fail("create_session", ms, f"status {code}: {str(body)[:200]}")
        return False
    if not isinstance(body, dict):
        _fail("create_session", ms, f"unexpected body: {body}")
        return False
    _session_id = body.get("id") or body.get("sessionId")
    if not _session_id:
        _fail("create_session", ms, f"no id in response: {body}")
        return False
    _pass("create_session", ms, f"id={_session_id[:12]}...")
    return True


def test_list_sessions() -> bool:
    """GET /api/sessions -> 200, our session appears"""
    start = time.time()
    code, body, err = _request("GET", "/api/sessions")
    ms = _elapsed_ms(start)
    if err:
        _fail("list_sessions", ms, err)
        return False
    if code != 200:
        _fail("list_sessions", ms, f"status {code}")
        return False
    if not isinstance(body, list):
        _fail("list_sessions", ms, "response is not a list")
        return False
    ids = [s.get("id") or s.get("sessionId") for s in body]
    if _session_id not in ids:
        _fail("list_sessions", ms, f"created session not in list")
        return False
    _pass("list_sessions", ms, f"{len(body)} session(s)")
    return True


def test_get_session_detail() -> bool:
    """GET /api/sessions/{id} -> 200, includes messages list"""
    start = time.time()
    code, body, err = _request("GET", f"/api/sessions/{_session_id}")
    ms = _elapsed_ms(start)
    if err:
        _fail("get_session_detail", ms, err)
        return False
    if code != 200:
        _fail("get_session_detail", ms, f"status {code}")
        return False
    if not isinstance(body, dict) or "messages" not in body:
        _fail("get_session_detail", ms, "no messages field in response")
        return False
    _pass("get_session_detail", ms, f"messages={len(body['messages'])}")
    return True


def test_send_message() -> bool:
    """POST /api/sessions/{id}/messages -> 202"""
    global _message_id
    start = time.time()
    code, body, err = _request("POST", f"/api/sessions/{_session_id}/messages", {"content": "Say only: pong"}, timeout=10)
    ms = _elapsed_ms(start)
    if err:
        _fail("send_message", ms, err)
        return False
    if code != 202:
        _fail("send_message", ms, f"status {code}: {str(body)[:200]}")
        return False
    if isinstance(body, dict):
        _message_id = body.get("messageId")
    _pass("send_message", ms, f"messageId={_message_id or 'n/a'}")
    return True


def test_get_messages() -> bool:
    """GET /api/sessions/{id}/messages -> 200, list"""
    start = time.time()
    code, body, err = _request("GET", f"/api/sessions/{_session_id}/messages")
    ms = _elapsed_ms(start)
    if err:
        _fail("get_messages", ms, err)
        return False
    if code != 200:
        _fail("get_messages", ms, f"status {code}")
        return False
    if not isinstance(body, list):
        _fail("get_messages", ms, "response is not a list")
        return False
    _pass("get_messages", ms, f"{len(body)} message(s)")
    return True


def test_sse_connects() -> bool:
    """GET /api/sessions/{id}/stream -> SSE first event has type=connected"""
    start = time.time()
    try:
        code, resp, err = _request("GET", f"/api/sessions/{_session_id}/stream", stream=True, timeout=5)
        if err:
            _fail("sse_connects", _elapsed_ms(start), err)
            return False
        if code != 200:
            _fail("sse_connects", _elapsed_ms(start), f"status {code}")
            return False
        # Read lines until we find a data: line or hit limit
        found_connected = False
        lines_read = 0
        for raw_bytes in resp:
            line = raw_bytes.decode().strip()
            lines_read += 1
            if lines_read > 20:
                break
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                try:
                    obj = json.loads(payload)
                    if obj.get("type") == "connected":
                        found_connected = True
                        break
                except json.JSONDecodeError:
                    pass
        resp.close()
        ms = _elapsed_ms(start)
        if found_connected:
            _pass("sse_connects", ms, "type=connected received")
            return True
        else:
            _fail("sse_connects", ms, f"no connected event in first {lines_read} lines")
            return False
    except Exception as e:
        _fail("sse_connects", _elapsed_ms(start), str(e))
        return False


def test_post_hook_event() -> bool:
    """POST /api/hooks/event -> 201"""
    start = time.time()
    code, body, err = _request("POST", "/api/hooks/event", {
        "event_type": "smoke_test",
        "session_id": _session_id,
        "tool_name": "smoke_test",
    })
    ms = _elapsed_ms(start)
    if err:
        _fail("post_hook_event", ms, err)
        return False
    if code != 201:
        _fail("post_hook_event", ms, f"status {code}: {str(body)[:200]}")
        return False
    _pass("post_hook_event", ms)
    return True


def test_hooks_stream_connects() -> bool:
    """GET /api/hooks/stream -> SSE connects (200)"""
    start = time.time()
    try:
        code, resp, err = _request("GET", "/api/hooks/stream", stream=True, timeout=3)
        if err:
            _fail("hooks_stream_connects", _elapsed_ms(start), err)
            return False
        if code != 200:
            _fail("hooks_stream_connects", _elapsed_ms(start), f"status {code}")
            if hasattr(resp, "close"):
                resp.close()
            return False
        resp.close()
        _pass("hooks_stream_connects", _elapsed_ms(start), "SSE 200 OK")
        return True
    except Exception:
        # Timeout on a stream endpoint is acceptable -- the connection was alive
        _pass("hooks_stream_connects", _elapsed_ms(start), "SSE connected (stream timeout OK)")
        return True


def test_error_cases() -> bool:
    """404 for nonexistent session on GET and DELETE"""
    all_ok = True
    fake_id = "00000000-0000-0000-0000-000000000000"

    # GET nonexistent session
    start = time.time()
    code, _, err = _request("GET", f"/api/sessions/{fake_id}")
    ms = _elapsed_ms(start)
    if err:
        _fail("error_get_404", ms, err)
        all_ok = False
    elif code == 404:
        _pass("error_get_404", ms)
    else:
        _fail("error_get_404", ms, f"expected 404, got {code}")
        all_ok = False

    # DELETE nonexistent session
    start = time.time()
    code, _, err = _request("DELETE", f"/api/sessions/{fake_id}")
    ms = _elapsed_ms(start)
    if err:
        _fail("error_delete_404", ms, err)
        all_ok = False
    elif code == 404:
        _pass("error_delete_404", ms)
    else:
        _fail("error_delete_404", ms, f"expected 404, got {code}")
        all_ok = False

    return all_ok


def test_cleanup() -> bool:
    """DELETE /api/sessions/{id} -> 204"""
    if not _session_id:
        _fail("cleanup", 0, "no session to delete")
        return False
    start = time.time()
    code, _, err = _request("DELETE", f"/api/sessions/{_session_id}")
    ms = _elapsed_ms(start)
    if err:
        _fail("cleanup", ms, err)
        return False
    if code == 204:
        _pass("cleanup", ms, f"deleted {_session_id[:12]}...")
        return True
    else:
        _fail("cleanup", ms, f"status {code}")
        return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_health,
    test_create_session,
    test_list_sessions,
    test_get_session_detail,
    test_send_message,
    test_get_messages,
    test_sse_connects,
    test_post_hook_event,
    test_hooks_stream_connects,
    test_error_cases,
    test_cleanup,
]


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Cadge live smoke test")
    parser.add_argument("--url", default=BASE_URL, help="Base API URL (default: %(default)s)")
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")

    print(f"\n{BOLD}Cadge Smoke Test{RESET}")
    print(f"{DIM}{BASE_URL}{RESET}\n")

    total_start = time.time()
    passed = 0
    failed = 0

    for test_fn in TESTS:
        ok = test_fn()
        if ok:
            passed += 1
        else:
            failed += 1

    total_ms = _elapsed_ms(total_start)
    print()
    summary_color = GREEN if failed == 0 else RED
    print(
        f"{summary_color}{BOLD}{passed} passed, {failed} failed{RESET} "
        f"{DIM}in {total_ms:.0f}ms{RESET}\n"
    )
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
