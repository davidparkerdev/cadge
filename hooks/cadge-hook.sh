#!/bin/bash

CADGE_API="http://localhost:33401"

INPUT=$(cat)

curl -s -X POST "${CADGE_API}/api/hooks/event" \
  -H "Content-Type: application/json" \
  -d "$INPUT" \
  --max-time 5 \
  > /dev/null 2>&1 &

exit 0
