import asyncio
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


def show(reply) -> None:
    if reply.HasField("task"):
        print(f"state={TaskState.Name(reply.task.status.state)} (snapshot)")
    elif reply.HasField("status_update"):
        su = reply.status_update
        line = f"state={TaskState.Name(su.status.state)}"
        if su.status.HasField("message"):
            line += f" text={get_message_text(su.status.message)}"
        print(line)
    elif reply.HasField("artifact_update"):
        au = reply.artifact_update
        print(
            f"artifact={au.artifact.name} artifactText={get_artifact_text(au.artifact)}"
        )


async def main() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

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

        try:
            msg = Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                parts=[Part(text="Hello from streaming demo!")],
            )

            task_id = None
            stream = client.send_message(SendMessageRequest(message=msg))
            async for reply in stream:
                show(reply)
                if task_id is None:
                    if reply.HasField("task"):
                        task_id = reply.task.id
                    elif reply.HasField("status_update"):
                        task_id = reply.status_update.task_id
                    if task_id is not None:
                        break

            await stream.aclose()

            await asyncio.sleep(5)

            print(f"\n--- resubscribe to {task_id} ---\n")
            async for reply in client.subscribe(SubscribeToTaskRequest(id=task_id)):
                show(reply)

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
