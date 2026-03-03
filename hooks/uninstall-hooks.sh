#!/bin/bash
# Uninstall Nexus v2 hooks from Claude Code settings
# This script safely removes only the nexus-v2 hook entries
# without affecting any other hooks in the settings.

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"

if [ ! -f "$SETTINGS_FILE" ]; then
    echo "No settings file found at $SETTINGS_FILE, nothing to uninstall."
    exit 0
fi

echo "Uninstalling Nexus v2 hooks..."
echo "  Settings file: $SETTINGS_FILE"

# Use python3 to safely remove nexus-v2 hooks from settings
SETTINGS_FILE="$SETTINGS_FILE" python3 << 'PYEOF'
import json
import os
import sys

settings_file = os.environ["SETTINGS_FILE"]

with open(settings_file, "r") as f:
    try:
        settings = json.load(f)
    except json.JSONDecodeError:
        print("  ERROR: Settings file contains invalid JSON, aborting.")
        sys.exit(1)

if "hooks" not in settings:
    print("  No hooks section found in settings, nothing to remove.")
    sys.exit(0)

hooks = settings["hooks"]
removed_count = 0

for event_name in list(hooks.keys()):
    event_rules = hooks[event_name]
    filtered_rules = []

    for rule in event_rules:
        # Filter out hooks that reference nexus-v2-hook.sh
        filtered_hooks = [
            h for h in rule.get("hooks", [])
            if not h.get("command", "").endswith("nexus-v2-hook.sh")
        ]

        if filtered_hooks:
            # Keep the rule but with nexus-v2 hooks removed
            rule["hooks"] = filtered_hooks
            filtered_rules.append(rule)
        elif rule.get("hooks") and not filtered_hooks:
            # All hooks in this rule were nexus-v2, drop the entire rule
            removed_count += 1
        else:
            # Rule had no hooks to begin with, keep it
            filtered_rules.append(rule)

    if filtered_rules:
        hooks[event_name] = filtered_rules
    else:
        # No rules left for this event, remove the event key entirely
        del hooks[event_name]

# If hooks section is now empty, remove it
if not hooks:
    del settings["hooks"]

# Write back
with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print(f"  Removed {removed_count} Nexus v2 hook entries")
print(f"  Settings written to {settings_file}")
PYEOF

echo "Done! Nexus v2 hooks have been removed."
echo "Restart any running Claude Code sessions for changes to take effect."
