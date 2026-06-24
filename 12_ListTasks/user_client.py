import asyncio

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

BASE_URL = "http://localhost:8001"
NUM_REQUESTS = 10


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
            for i in range(1, NUM_REQUESTS + 1):
                request = SendMessageRequest(
                    message=new_text_message(text=f"job #{i}", role=Role.ROLE_USER)
                )
                async for _ in client.send_message(request):
                    pass
                print(f"sent {i}/{NUM_REQUESTS}")
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
