import json

import uvicorn
from fastapi import FastAPI, Header, Request
from google.protobuf.json_format import MessageToDict, Parse

from a2a.types import Task

HOST = "127.0.0.1"
PORT = 3000

app = FastAPI()


@app.post("/webhook")
async def webhook(
    request: Request,
    token: str | None = Header(default=None, alias="X-A2A-Notification-Token"),
):
    body = await request.body()
    task = Parse(body.decode("utf-8"), Task())

    print("\n--- PUSH TASK ---")
    if token:
        print(f"token={token}")

    print(
        json.dumps(
            MessageToDict(task, preserving_proto_field_name=True),
            ensure_ascii=False,
            indent=2,
        )
    )
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
