import asyncio

import httpx
import typer

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(text: str = typer.Option("Hello from 03_Tasks!")) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient() as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await create_client(
                card,
                client_config=ClientConfig(
                    supported_protocol_bindings=[
                        card.supported_interfaces[0].protocol_binding
                    ],
                    httpx_client=http,
                ),
            )

            try:
                request = SendMessageRequest(
                    message=new_text_message(text=text, role=Role.ROLE_USER)
                )
                async for reply in client.send_message(request):
                    print(reply)
                    break
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
