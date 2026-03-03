#!/bin/bash
# Install Nexus v2 hooks into Claude Code settings
# This script safely merges hook configuration into ~/.claude/settings.json
# without overwriting any existing settings.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_SCRIPT="${SCRIPT_DIR}/nexus-v2-hook.sh"
SETTINGS_FILE="$HOME/.claude/settings.json"

# Ensure the hook script is executable
chmod +x "$HOOK_SCRIPT"

# Ensure ~/.claude directory exists
mkdir -p "$HOME/.claude"

echo "Installing Nexus v2 hooks..."
echo "  Hook script: $HOOK_SCRIPT"
echo "  Settings file: $SETTINGS_FILE"

# Use python3 to safely merge hook config into existing settings
HOOK_SCRIPT="$HOOK_SCRIPT" SETTINGS_FILE="$SETTINGS_FILE" python3 << 'PYEOF'
import json
import os
import sys

settings_file = os.environ["SETTINGS_FILE"]
hook_script = os.environ["HOOK_SCRIPT"]

# Read existing settings or start fresh
if os.path.exists(settings_file):
    with open(settings_file, "r") as f:
        try:
            settings = json.load(f)
        except json.JSONDecodeError:
            print(f"  WARNING: {settings_file} contains invalid JSON, backing up and starting fresh")
            import shutil
            shutil.copy2(settings_file, settings_file + ".bak")
            settings = {}
else:
    settings = {}

# Define the hook events to register
hook_events = [
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "TaskCompleted",
    "PreCompact",
]

# Build the nexus v2 hook entry for each event
nexus_hook_entry = {
    "type": "command",
    "command": hook_script,
    "timeout": 10,
}

# Ensure hooks section exists
if "hooks" not in settings:
    settings["hooks"] = {}

hooks = settings["hooks"]

for event_name in hook_events:
    if event_name not in hooks:
        hooks[event_name] = []

    event_rules = hooks[event_name]

    # Check if a nexus-v2 hook already exists for this event
    already_installed = False
    for rule in event_rules:
        for hook in rule.get("hooks", []):
            if hook.get("command", "").endswith("nexus-v2-hook.sh"):
                # Update the existing entry to current path/timeout
                hook["command"] = hook_script
                hook["timeout"] = 10
                already_installed = True

    if not already_installed:
        # Add a new rule with empty matcher (matches everything)
        event_rules.append({
            "matcher": "",
            "hooks": [nexus_hook_entry.copy()],
        })

# Write back
with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"  Installed hooks for {len(hook_events)} event types")
print(f"  Settings written to {settings_file}")
PYEOF

echo "Done! Nexus v2 hooks are now active."
echo "Restart any running Claude Code sessions for hooks to take effect."
