#!/bin/bash
# Stargate Stop - kills any running Stargate processes by port

API_PORT=33401
UI_PORT=33400

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

stopped=0

for port in $API_PORT $UI_PORT; do
    pids=$(lsof -t -i :"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            kill "$pid" 2>/dev/null
            echo -e "${YELLOW}Killed${NC} process $pid on port $port"
            stopped=1
        done
    fi
done

if [ "$stopped" -eq 0 ]; then
    echo -e "${GREEN}No Stargate processes running.${NC}"
else
    echo -e "${GREEN}Stargate stopped.${NC}"
fi
