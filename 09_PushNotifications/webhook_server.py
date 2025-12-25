import json

import uvicorn
from fastapi import FastAPI, Header

from a2a.types import Task

HOST = "127.0.0.1"
PORT = 3000

app = FastAPI()


@app.post("/webhook")
async def webhook(
    task: Task,
    token: str | None = Header(default=None, alias="X-A2A-Notification-Token"),
):
    print("\n--- PUSH TASK ---")
    if token:
        print(f"token={token}")

    print(
        json.dumps(
            task.model_dump(mode="json", by_alias=True, exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
    )
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
