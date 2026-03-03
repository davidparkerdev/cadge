# Nexus v2 - Claude Code Hooks

Hooks that stream Claude Code lifecycle events to the Nexus v2 API in real time. This gives Nexus v2 full visibility into what Claude Code sessions are doing -- tool calls, prompts, session starts/stops, errors, and more.

## How it works

A single shell script (`nexus-v2-hook.sh`) handles all event types. Claude Code pipes JSON to the script on stdin for each lifecycle event. The script POSTs that JSON to the Nexus v2 API and exits immediately (fire-and-forget via background curl) so it never blocks Claude Code.

## Events covered

| Event | Description |
|-------|-------------|
| `SessionStart` | A Claude Code session begins |
| `SessionEnd` | A Claude Code session ends |
| `UserPromptSubmit` | User submits a prompt |
| `PreToolUse` | Before a tool is executed |
| `PostToolUse` | After a tool completes successfully |
| `PostToolUseFailure` | After a tool fails |
| `Notification` | Claude Code sends a notification |
| `Stop` | Claude stops generating |
| `SubagentStart` | A sub-agent (Task tool) starts |
| `SubagentStop` | A sub-agent finishes |
| `TaskCompleted` | A task completes |
| `PreCompact` | Before conversation compaction |

## Install

```bash
./install-hooks.sh
```

This merges hook configuration into `~/.claude/settings.json` without overwriting existing settings. Restart any running Claude Code sessions after installing.

## Uninstall

```bash
./uninstall-hooks.sh
```

Removes only the Nexus v2 hook entries, leaving all other settings and hooks intact.

## API endpoint

All events are POSTed to:

```
POST http://localhost:33382/api/hooks/event
Content-Type: application/json
```

The full JSON payload from Claude Code is forwarded as-is. The `hook_event_name` field in the payload identifies the event type.

## Future: PreToolUse approval flow

The `PreToolUse` event can be extended to support an approval/rejection flow. Instead of fire-and-forget, the hook would:

1. POST the event to the API
2. Wait for a response with an approval decision
3. Return the decision to Claude Code (approve, reject, or modify)

This would allow Nexus v2 to act as a gatekeeper for tool execution. The hook script and API endpoint are designed with this extension in mind.
