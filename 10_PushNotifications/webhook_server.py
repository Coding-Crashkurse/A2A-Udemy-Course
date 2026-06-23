import json

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from google.protobuf.json_format import MessageToDict, Parse

from a2a.types import StreamResponse

HOST = "127.0.0.1"
PORT = 3000

EXPECTED_TOKEN = "demo-token"

app = FastAPI()


@app.post("/webhook")
async def webhook(
    request: Request,
    token: str | None = Header(default=None, alias="X-A2A-Notification-Token"),
):
    if token != EXPECTED_TOKEN:
        print("\n--- PUSH EVENT REJECTED ---")
        print("missing token" if token is None else f"invalid token={token}")
        raise HTTPException(
            status_code=401, detail="Invalid or missing notification token"
        )

    body = await request.body()
    event = Parse(body.decode("utf-8"), StreamResponse())

    print("\n--- PUSH EVENT ---")
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
