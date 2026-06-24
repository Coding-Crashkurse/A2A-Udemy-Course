import asyncio
import uuid

import httpx

from a2a.client import Client, ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    Task,
    TaskState,
)

BASE_URL = "http://localhost:8001"


async def send_turn(client: Client, msg: Message) -> Task:
    request = SendMessageRequest(message=msg)
    [reply] = [r async for r in client.send_message(request)]
    return reply.task


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
                streaming=False,
                polling=False,
            ),
        )

        try:
            print("\n--- TURN 1 (request/response) ---\n")
            task = await send_turn(
                client,
                Message(
                    role=Role.ROLE_USER,
                    message_id=str(uuid.uuid4()),
                    parts=[Part(text="Start Multi-Turn")],
                ),
            )
            print(f"state={TaskState.Name(task.status.state)}")
            print(f"agent asks: {get_message_text(task.status.message)}")

            if task.status.state != TaskState.TASK_STATE_INPUT_REQUIRED:
                raise RuntimeError(
                    f"Expected input_required, got {TaskState.Name(task.status.state)}"
                )

            print("\n--- TURN 2 (same task_id) ---\n")
            task = await send_turn(
                client,
                Message(
                    role=Role.ROLE_USER,
                    message_id=str(uuid.uuid4()),
                    task_id=task.id,
                    context_id=task.context_id,
                    parts=[Part(text="Markus")],
                ),
            )
            print(f"state={TaskState.Name(task.status.state)}")
            for artifact in task.artifacts:
                print(f"artifact={artifact.name} text={get_artifact_text(artifact)}")

            if task.status.state != TaskState.TASK_STATE_COMPLETED:
                raise RuntimeError(
                    f"Expected completed, got {TaskState.Name(task.status.state)}"
                )

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
