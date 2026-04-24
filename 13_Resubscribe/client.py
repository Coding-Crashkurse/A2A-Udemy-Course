import asyncio
import time
import uuid

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    TaskState,
)

BASE_URL = "http://localhost:8001"

KILL_AFTER_SECONDS = 6.0
OFFLINE_SECONDS = 3.0


def fmt_stream_response(reply) -> str:
    if reply.HasField("task"):
        t = reply.task
        return f"state={TaskState.Name(t.status.state)} (snapshot)"
    if reply.HasField("status_update"):
        su = reply.status_update
        line = f"state={TaskState.Name(su.status.state)}"
        if su.status.HasField("message"):
            line += f" text={get_message_text(su.status.message)}"
        return line
    if reply.HasField("artifact_update"):
        au = reply.artifact_update
        return (
            f"artifact={au.artifact.name}"
            f" artifactText={get_artifact_text(au.artifact)}"
        )
    return "<unknown>"


async def connect_streaming_client(card):
    http = httpx.AsyncClient(timeout=None)
    client = await create_client(
        card,
        client_config=ClientConfig(
            supported_protocol_bindings=[
                card.supported_interfaces[0].protocol_binding
            ],
            httpx_client=http,
            streaming=True,
            polling=False,
        ),
    )
    return client


async def main() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

    client1 = await connect_streaming_client(card)

    task_id: str | None = None
    context_id: str | None = None

    print("\n=== START STREAM (message:stream) ===\n")
    start_msg = Message(
        role=Role.ROLE_USER,
        message_id=str(uuid.uuid4()),
        parts=[Part(text="Start SubscribeToTask demo")],
    )

    async def _read_initial_stream() -> None:
        nonlocal task_id, context_id
        try:
            request = SendMessageRequest(message=start_msg)
            async for reply in client1.send_message(request):
                if task_id is None:
                    if reply.HasField("task"):
                        task_id = reply.task.id
                        context_id = reply.task.context_id
                    elif reply.HasField("status_update"):
                        task_id = reply.status_update.task_id
                        context_id = reply.status_update.context_id
                    if task_id is not None:
                        print(f"(stream-1) taskId={task_id} contextId={context_id}")
                print(f"(stream-1) {fmt_stream_response(reply)}")
        except Exception as e:
            print(f"(stream-1) disconnected: {type(e).__name__}: {e}")

    reader_task = asyncio.create_task(_read_initial_stream())

    t0 = time.perf_counter()
    while task_id is None:
        if time.perf_counter() - t0 > 5.0:
            raise RuntimeError("Did not receive task id within 5s")
        await asyncio.sleep(0.05)

    print(
        f"\n>>> wait {KILL_AFTER_SECONDS:.1f}s then KILL connection (close client #1) ...\n"
    )
    await asyncio.sleep(KILL_AFTER_SECONDS)

    await client1.close()

    await reader_task

    print(f"\n>>> offline for {OFFLINE_SECONDS:.1f}s ...\n")
    await asyncio.sleep(OFFLINE_SECONDS)

    print("\n=== RESUBSCRIBE (SubscribeToTask) ===\n")
    client2 = await connect_streaming_client(card)

    try:
        assert task_id is not None
        async for reply in client2.subscribe(SubscribeToTaskRequest(id=task_id)):
            print(f"(stream-2) {fmt_stream_response(reply)}")
    finally:
        await client2.close()

    print("\n=== DONE ===\n")


if __name__ == "__main__":
    asyncio.run(main())
