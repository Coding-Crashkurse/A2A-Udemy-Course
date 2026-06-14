"""Minimal A2A error-handling demo client.

Provokes a few catalog errors and shows, for each one:
  * the raw wire view   -> HTTP status + the ErrorInfo / problem JSON body
  * the three representations of the SAME logical error (HTTP / JSON-RPC / gRPC)
  * clean, typed catching with the high-level client (it re-raises an A2AError)
"""

import asyncio
import json
import uuid

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import (
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
)
from a2a.utils.errors import (
    A2A_REST_ERROR_MAPPING,
    JSON_RPC_ERROR_CODE_MAP,
    A2AError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

BASE_URL = "http://localhost:8014"
HDRS = {"A2A-Version": "1.0"}


def show_mapping(err_cls: type[A2AError]) -> None:
    """Print how this single error looks on each transport."""
    rest = A2A_REST_ERROR_MAPPING[err_cls]
    jsonrpc = JSON_RPC_ERROR_CODE_MAP.get(err_cls, "?")
    print(
        f"   same error, three representations -> "
        f"HTTP {rest.http_code} | JSON-RPC {jsonrpc} | gRPC {rest.grpc_status}"
    )


def show_wire(label: str, status: int, body: str) -> None:
    print(f"\n=== {label} ===")
    print(f"   HTTP status : {status}")
    try:
        print("   problem JSON:", json.dumps(json.loads(body), indent=2))
    except json.JSONDecodeError:
        print("   body        :", body[:300])


async def make_completed_task(client) -> Task:
    """Create a task and let it run to completion (blocking send)."""
    msg = Message(
        role=Role.ROLE_USER,
        message_id=str(uuid.uuid4()),
        context_id=str(uuid.uuid4()),
        parts=[Part(text="do a quick job")],
    )
    task: Task | None = None
    async for reply in client.send_message(SendMessageRequest(message=msg)):
        if reply.HasField("task"):
            task = reply.task
    return task


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()
        client = await create_client(
            card,
            client_config=ClientConfig(
                supported_protocol_bindings=[card.supported_interfaces[0].protocol_binding],
                httpx_client=http,
                streaming=False,
                polling=False,
            ),
        )

        try:
            # ---- ERROR 1: task-not-found (404 / -32001) ----
            r = await http.get(f"{BASE_URL}/v1/tasks/does-not-exist", headers=HDRS)
            show_wire("ERROR 1  GET unknown task -> task-not-found", r.status_code, r.text)
            show_mapping(TaskNotFoundError)

            # ---- ERROR 2: unsupported-operation (400 / -32004) ----
            # message:stream on a streaming=False agent. Body built via the SDK
            # so it parses correctly; the agent rejects the operation.
            stream_req = SendMessageRequest(
                message=Message(
                    role=Role.ROLE_USER,
                    message_id=str(uuid.uuid4()),
                    parts=[Part(text="stream please")],
                )
            )
            r = await http.post(
                f"{BASE_URL}/v1/message:stream",
                json=MessageToDict(stream_req),
                headers=HDRS,
            )
            show_wire("ERROR 2  message:stream on non-streaming agent -> unsupported-operation", r.status_code, r.text)
            show_mapping(UnsupportedOperationError)

            # ---- ERROR 3: task-not-cancelable (409 / -32002) ----
            done = await make_completed_task(client)
            print(f"\n(created + completed task {done.id} to cancel it illegally)")
            r = await http.post(
                f"{BASE_URL}/v1/tasks/{done.id}:cancel", json={}, headers=HDRS
            )
            show_wire("ERROR 3  cancel a completed task -> task-not-cancelable", r.status_code, r.text)
            show_mapping(TaskNotCancelableError)

            # ---- Clean, typed catching with the high-level client ----
            print("\n=== Clean client-side handling (typed A2AError) ===")
            try:
                await client.get_task(GetTaskRequest(id="does-not-exist"))
            except TaskNotFoundError as e:
                print(f"   caught typed TaskNotFoundError: {e.message!r} (handled gracefully)")

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
