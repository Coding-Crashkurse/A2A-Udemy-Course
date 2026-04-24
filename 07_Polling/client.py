import asyncio
import uuid

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text
from a2a.types import (
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
)

BASE_URL = "http://localhost:8001"
POLL_INTERVAL_SECONDS = 1.0


def current_status_text(task: Task) -> str:
    if task.status.message and task.status.message.parts:
        return get_message_text(task.status.message)

    last_msg = task.history[-1]
    return get_message_text(last_msg)


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await create_client(
            card,
            client_config=ClientConfig(
                supported_protocol_bindings=[
                    card.supported_interfaces[0].protocol_binding
                ],
                httpx_client=http,
                polling=True,
                streaming=False,
            ),
        )

        try:
            msg = Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                parts=[Part(text="Hello from polling demo!")],
            )

            request = SendMessageRequest(message=msg)
            task: Task | None = None
            async for reply in client.send_message(request):
                if reply.HasField("task"):
                    task = reply.task
                    break

            print(f"taskId={task.id}")
            print(f"contextId={task.context_id}")
            print(f"initialState={TaskState.Name(task.status.state)}")

            poll_no = 0
            while True:
                poll_no += 1
                task = await client.get_task(GetTaskRequest(id=task.id))

                text = current_status_text(task)
                print(
                    f"poll={poll_no} state={TaskState.Name(task.status.state)} text={text}"
                )

                if task.status.state == TaskState.TASK_STATE_COMPLETED:
                    break

                await asyncio.sleep(POLL_INTERVAL_SECONDS)

            artifact = task.artifacts[-1]
            artifact_text = artifact.parts[0].text
            print(f"\nartifactName={artifact.name}")
            print(f"artifactText={artifact_text}")

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
