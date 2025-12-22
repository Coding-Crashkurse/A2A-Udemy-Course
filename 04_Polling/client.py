import asyncio
import uuid

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import Message, Part, Role, TaskQueryParams, TaskState, TextPart, Task

BASE_URL = "http://localhost:8001"
POLL_INTERVAL_SECONDS = 1.0


def current_status_text(task: Task) -> str:
    if task.status.message and task.status.message.parts:
        return task.status.message.parts[0].root.text

    last_msg = task.history[-1]
    return last_msg.parts[0].root.text


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
                polling=True,
                streaming=False,
            ),
        )

        try:
            msg = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="Hello from polling demo!"))],
            )

            task, _ = await anext(client.send_message(msg))

            print(f"taskId={task.id}")
            print(f"contextId={task.context_id}")
            print(f"initialState={task.status.state}")

            poll_no = 0
            while True:
                poll_no += 1
                task = await client.get_task(TaskQueryParams(id=task.id))

                text = current_status_text(task)
                print(f"poll={poll_no} state={task.status.state} text={text}")

                if task.status.state == TaskState.completed:
                    break

                await asyncio.sleep(POLL_INTERVAL_SECONDS)

            artifact = task.artifacts[-1]
            artifact_text: TextPart = artifact.parts[0].root
            print(f"\nartifactName={artifact.name}")
            print(f"artifactText={artifact_text.text}")

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
