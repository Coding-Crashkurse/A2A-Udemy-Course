import json
import sys

import uvicorn
from fastapi import FastAPI, Header, Request
from google.protobuf.json_format import MessageToDict, Parse

from a2a.types import StreamResponse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HOST = "127.0.0.1"
PORT = 3000

app = FastAPI()


@app.post("/webhook")
async def webhook(
    request: Request,
    token: str | None = Header(default=None, alias="X-A2A-Notification-Token"),
):
    body = await request.body()
    event = Parse(body.decode("utf-8"), StreamResponse())

    print("\n--- PUSH EVENT ---")
    if token:
        print(f"token={token}")

    for field in ("task", "message", "status_update", "artifact_update"):
        if event.HasField(field):
            print(f"kind={field}")
            break
    print(
        json.dumps(
            MessageToDict(event, preserving_proto_field_name=True),
            ensure_ascii=False,
            indent=2,
        )
    )
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
