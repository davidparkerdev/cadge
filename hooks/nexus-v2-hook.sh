#!/bin/bash
# Nexus v2 Hook - Posts Claude Code lifecycle events to Nexus v2 API
# Used by all hook event types: SessionStart, SessionEnd, PreToolUse, PostToolUse, etc.
#
# This script reads JSON from stdin and POSTs it to the Nexus v2 hooks endpoint.
# It runs as fire-and-forget to avoid blocking Claude Code.

NEXUS_API="http://localhost:33401"

# Read the full JSON payload from stdin
INPUT=$(cat)

# Post event to Nexus v2 (fire and forget, don't block Claude)
curl -s -X POST "${NEXUS_API}/api/hooks/event" \
  -H "Content-Type: application/json" \
  -d "$INPUT" \
  --max-time 5 \
  > /dev/null 2>&1 &

exit 0
