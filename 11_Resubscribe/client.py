import asyncio
import time
import uuid

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskIdParams,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import get_artifact_text, get_message_text

BASE_URL = "http://localhost:8001"

KILL_AFTER_SECONDS = 6.0          # wie lange wir die erste Stream-Verbindung laufen lassen
OFFLINE_SECONDS = 3.0             # wie lange wir "offline" sind, bevor wir resubscriben


def fmt_update(task: Task, update) -> str:
    state = task.status.state.value if task.status and task.status.state else "<?>"
    line = f"state={state}"

    if update is None:
        line += " (snapshot)"

    if isinstance(update, TaskStatusUpdateEvent) and update.status.message:
        line += f" text={get_message_text(update.status.message)}"

    if isinstance(update, TaskArtifactUpdateEvent):
        line += f" artifact={update.artifact.name} artifactText={get_artifact_text(update.artifact)}"

    return line


async def connect_streaming_client(card) -> object:
    """
    Create a fresh client with its own httpx client.
    Important: RestTransport.close() closes its httpx client, so don't share.
    """
    http = httpx.AsyncClient(timeout=None)
    client = await ClientFactory.connect(
        card,
        client_config=ClientConfig(
            supported_transports=[card.preferred_transport],
            httpx_client=http,
            streaming=True,
            polling=False,
        ),
    )
    return client


async def main() -> None:
    # 0) Card holen (separater httpx client)
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

    # 1) Start via message:stream (Client #1)
    client1 = await connect_streaming_client(card)

    task_id: str | None = None
    context_id: str | None = None

    print("\n=== START STREAM (message:stream) ===\n")
    start_msg = Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        parts=[Part(root=TextPart(text="Start SubscribeToTask demo"))],
    )

    # Wir lesen in einer Background-Task, damit wir nach X Sekunden "hart" killen können.
    async def _read_initial_stream() -> None:
        nonlocal task_id, context_id
        it = client1.send_message(start_msg)

        try:
            async for task, update in it:
                if task_id is None:
                    task_id = task.id
                    context_id = task.context_id
                    print(f"(stream-1) taskId={task_id} contextId={context_id}")

                # Ausgabe
                if update is not None:
                    print(f"(stream-1) {fmt_update(task, update)}")
        except Exception as e:
            # Bei einem "Connection kill" ist ein Exception/Cancel hier normal
            print(f"(stream-1) disconnected: {type(e).__name__}: {e}")
        finally:
            try:
                await it.aclose()
            except Exception:
                pass

    reader_task = asyncio.create_task(_read_initial_stream())

    # warten bis wir task_id haben
    t0 = time.perf_counter()
    while task_id is None:
        if time.perf_counter() - t0 > 5.0:
            raise RuntimeError("Did not receive task id within 5s")
        await asyncio.sleep(0.05)

    # 2) Connection killen
    print(f"\n>>> wait {KILL_AFTER_SECONDS:.1f}s then KILL connection (close client #1) ...\n")
    await asyncio.sleep(KILL_AFTER_SECONDS)

    # "hard-ish" kill: close transport (closes underlying httpx client/socket)
    await client1.close()

    # sicherstellen, dass reader endet
    await reader_task

    print(f"\n>>> offline for {OFFLINE_SECONDS:.1f}s ...\n")
    await asyncio.sleep(OFFLINE_SECONDS)

    # 3) Resubscribe (Client #2)
    print("\n=== RESUBSCRIBE (SubscribeToTask) ===\n")
    client2 = await connect_streaming_client(card)

    try:
        assert task_id is not None
        async for task, update in client2.resubscribe(TaskIdParams(id=task_id)):
            # Bei resubscribe bekommst du i.d.R. zuerst einen Snapshot (update=None) und dann Events.
            print(f"(stream-2) {fmt_update(task, update)}")
    finally:
        await client2.close()

    print("\n=== DONE ===\n")


if __name__ == "__main__":
    asyncio.run(main())
