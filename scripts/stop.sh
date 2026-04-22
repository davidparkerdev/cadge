#!/bin/bash
# Cadge Stop - kills any running Cadge processes by port

API_PORT=33401
UI_PORT=33400

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

stopped=0

# Uses netstat (PF_ROUTE sysctls), not lsof. lsof on macOS 26 has triggered
# reproducible kernel panics (NULL+0x48 in proc/file-table iteration).
for port in $API_PORT $UI_PORT; do
    pids=$(netstat -anv -p tcp 2>/dev/null \
        | awk -v p="$port" '$0 ~ /LISTEN/ && $4 ~ ("\\."p"$") {
            for (i=1; i<=NF; i++) if ($i ~ /:[0-9]+$/) { n=split($i,a,":"); print a[n]; break }
          }' \
        | sort -u)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            kill "$pid" 2>/dev/null
            echo -e "${YELLOW}Killed${NC} process $pid on port $port"
            stopped=1
        done
    fi
done

if [ "$stopped" -eq 0 ]; then
    echo -e "${GREEN}No Cadge processes running.${NC}"
else
    echo -e "${GREEN}Cadge stopped.${NC}"
fi
