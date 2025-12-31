import asyncio
import uuid

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
)

BASE_URL = "http://localhost:8001"


def parts_text(parts: list[Part]) -> str:
    out: list[str] = []
    for p in parts:
        root = getattr(p, "root", None)
        text = getattr(root, "text", None)
        if text:
            out.append(text)
    return " ".join(out).strip()


async def main() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
                streaming=True,
                polling=False,
            ),
        )

        try:
            msg = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="Hello from streaming demo!"))],
            )

            async for task, update in client.send_message(msg):
                line = f"state={task.status.state.value}"

                if isinstance(update, TaskStatusUpdateEvent) and update.status.message:
                    line += f" text={parts_text(update.status.message.parts)}"

                if isinstance(update, TaskArtifactUpdateEvent):
                    line += (
                        f" artifact={update.artifact.name}"
                        f" artifactText={parts_text(update.artifact.parts)}"
                    )

                print(line)

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
