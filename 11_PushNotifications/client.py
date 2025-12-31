import asyncio
import uuid

import httpx
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    MessageSendConfiguration,
    Part,
    PushNotificationConfig,
    Role,
    TaskPushNotificationConfig,
    TextPart,
)

AGENT_BASE_URL = "http://127.0.0.1:8001"
WEBHOOK_URL = "http://127.0.0.1:3000/webhook"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        card = await A2ACardResolver(http, AGENT_BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
                streaming=False,
                polling=False,
            ),
        )

        try:
            msg = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="Trigger Push Workflow"))],
            )

            # Request wirklich rausschicken (minimal, ohne loop)
            event_iter = client.send_message(
                msg,
                configuration=MessageSendConfiguration(blocking=False),
            )
            task, _update = await anext(event_iter)
            await event_iter.aclose()

            # Callback setzen (das ist der entscheidende Teil für Push)
            push_cfg = PushNotificationConfig(
                url=WEBHOOK_URL,
                id=str(uuid.uuid4()),
                token="demo-token",
            )
            await client.set_task_callback(
                TaskPushNotificationConfig(
                    task_id=task.id,
                    push_notification_config=push_cfg,
                )
            )

            print(
                f"taskId={task.id} contextId={task.context_id} state={task.status.state.value}"
            )

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
