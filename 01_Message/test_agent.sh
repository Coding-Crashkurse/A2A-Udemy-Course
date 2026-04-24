#!/bin/bash

URL="http://localhost:8000/"
CONTENT_TYPE="Content-Type: application/json"


PAYLOAD='{
  "jsonrpc": "2.0",
  "id": "req-1",
  "method": "SendMessage",
  "params": {
    "message": {
      "role": "ROLE_USER",
      "message_id": "msg-client-001",
      "parts": [
        { "text": "Hello A2A World!" }
      ]
    }
  }
}'

echo "----------------------------------------"
echo "Sending POST request to $URL..."
echo "Payload: $PAYLOAD"
echo "----------------------------------------"

response=$(curl -s -X POST "$URL" -H "$CONTENT_TYPE" -H "A2A-Version: 1.0" -d "$PAYLOAD")

if command -v jq &> /dev/null; then
    echo "Response:"
    echo "$response" | jq .
else
    echo "Response (Raw):"
    echo "$response"
fi
echo "----------------------------------------"
