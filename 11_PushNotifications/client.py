import asyncio
import uuid

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    TaskPushNotificationConfig,
    TaskState,
)

AGENT_BASE_URL = "http://127.0.0.1:8001"
WEBHOOK_URL = "http://127.0.0.1:3000/webhook"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        card = await A2ACardResolver(http, AGENT_BASE_URL).get_agent_card()

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
            msg = Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                parts=[Part(text="Trigger Push Workflow")],
            )

            request = SendMessageRequest(
                message=msg,
                configuration=SendMessageConfiguration(return_immediately=True),
            )
            task = None
            async for reply in client.send_message(request):
                if reply.HasField("task"):
                    task = reply.task
                    break

            await client.create_task_push_notification_config(
                TaskPushNotificationConfig(
                    task_id=task.id,
                    id=str(uuid.uuid4()),
                    url=WEBHOOK_URL,
                    token="demo-token",
                )
            )

            print(
                f"taskId={task.id} contextId={task.context_id} state={TaskState.Name(task.status.state)}"
            )

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
