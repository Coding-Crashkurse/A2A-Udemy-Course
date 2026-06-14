import asyncio
import time
import uuid
from typing import Any

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    Task,
    TaskState,
)

BASE_URL = "http://localhost:8001"


def fmt_task_line(t: Task) -> str:
    state = TaskState.Name(t.status.state) if t.status else "<?>"
    msg = get_message_text(t.status.message) if t.status and t.status.HasField("message") else ""
    return f"taskId={t.id} contextId={t.context_id} state={state} statusText={msg!r}"


async def create_task_fire_and_forget(client, *, context_id: str, text: str) -> Task:
    msg = Message(
        role=Role.ROLE_USER,
        message_id=str(uuid.uuid4()),
        context_id=context_id,
        parts=[Part(text=text)],
    )

    request = SendMessageRequest(
        message=msg,
        configuration=SendMessageConfiguration(return_immediately=True),
    )
    task: Task | None = None
    async for reply in client.send_message(request):
        if reply.HasField("task"):
            task = reply.task
            break
    return task


async def list_tasks_rest(
    http: httpx.AsyncClient,
    *,
    base_url: str,
    context_id: str,
    status: str | None,
    include_artifacts: bool,
    page_size: int,
    page_token: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {
        "contextId": context_id,
        "includeArtifacts": str(include_artifacts).lower(),
        "pageSize": page_size,
    }
    if status:
        params["status"] = status
    if page_token:
        params["pageToken"] = page_token

    r = await http.get(
        f"{base_url}/v1/tasks",
        params=params,
        headers={"A2A-Version": "1.0"},
    )
    r.raise_for_status()
    data = r.json()
    return data.get("tasks", []), data.get("nextPageToken")


def print_list(title: str, tasks: list[dict[str, Any]], next_token: str | None) -> None:
    print(f"\n{title}")
    print(f"count={len(tasks)} nextPageToken={next_token!r}")
    for t in tasks:
        tid = t.get("id")
        cid = t.get("context_id") or t.get("contextId")
        state = (t.get("status") or {}).get("state")

        artifacts = t.get("artifacts")
        artifact_names = []
        if isinstance(artifacts, list):
            artifact_names = [a.get("name") for a in artifacts]

        print(f"  - id={tid} contextId={cid} state={state} artifacts={artifact_names}")


async def main() -> None:
    context_id = str(uuid.uuid4())
    print(f"contextId (shared) = {context_id}")

    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await create_client(
            card,
            client_config=ClientConfig(
                supported_protocol_bindings=[
                    card.supported_interfaces[0].protocol_binding
                ],
                httpx_client=http,
                streaming=False,
                polling=False,
            ),
        )

        try:
            created: list[Task] = []
            for i in range(1, 4):
                t = await create_task_fire_and_forget(
                    client,
                    context_id=context_id,
                    text=f"Create job #{i}",
                )
                created.append(t)
                print(f"\ncreated[{i}]: {fmt_task_line(t)}")

            page1, next1 = await list_tasks_rest(
                http,
                base_url=BASE_URL,
                context_id=context_id,
                status=None,
                include_artifacts=False,
                page_size=2,
                page_token=None,
            )
            print_list("LIST (immediately, page 1)", page1, next1)

            if next1:
                page2, next2 = await list_tasks_rest(
                    http,
                    base_url=BASE_URL,
                    context_id=context_id,
                    status=None,
                    include_artifacts=False,
                    page_size=2,
                    page_token=next1,
                )
                print_list("LIST (immediately, page 2)", page2, next2)

            await asyncio.sleep(1.0)
            working, next_w = await list_tasks_rest(
                http,
                base_url=BASE_URL,
                context_id=context_id,
                status="working",
                include_artifacts=False,
                page_size=50,
                page_token=None,
            )
            print_list("LIST (filter status=working)", working, next_w)

            print("\nwaiting ~35s so tasks can complete...")
            t0 = time.perf_counter()
            await asyncio.sleep(35.0)
            print(f"waited={time.perf_counter() - t0:.2f}s")

            completed, next_c = await list_tasks_rest(
                http,
                base_url=BASE_URL,
                context_id=context_id,
                status="completed",
                include_artifacts=True,
                page_size=50,
                page_token=None,
            )
            print_list(
                "LIST (filter status=completed, includeArtifacts=true)",
                completed,
                next_c,
            )

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
