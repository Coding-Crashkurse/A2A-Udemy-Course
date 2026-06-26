import asyncio
from uuid import uuid4

import httpx
from google.protobuf.struct_pb2 import Struct

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils import TransportProtocol
from a2a.utils.errors import A2AError

BASE_URL = "http://localhost:8001"


def build_message(text: str, chat_id: str | None, extension_uri: str) -> Message:
    metadata = Struct()
    if chat_id is not None:
        metadata.update({extension_uri: {"chat_id": chat_id}})
    return Message(
        role=Role.ROLE_USER,
        message_id=str(uuid4()),
        parts=[Part(text=text)],
        metadata=metadata,
    )


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        extension_uri = next(
            (ext.uri for ext in card.capabilities.extensions if ext.required),
            None,
        )
        if extension_uri is None:
            raise RuntimeError("Agent card declares no required extension")
        print(f"Discovered required extension: {extension_uri}")

        client = await create_client(
            card,
            client_config=ClientConfig(
                supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
                httpx_client=http,
                streaming=False,
                polling=False,
            ),
        )

        for chat_id in (None, "not-a-uuid", str(uuid4())):
            print(f"\n=== chat_id={chat_id} ===")
            request = SendMessageRequest(
                message=build_message("Hello there", chat_id, extension_uri)
            )
            try:
                async for reply in client.send_message(request):
                    if reply.HasField("task") and reply.task.status.HasField("message"):
                        print(get_message_text(reply.task.status.message))
                        break
            except A2AError as exc:
                print(f"Rejected by server -> {exc}")

        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
