import asyncio

import httpx
import typer

from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(text: str = typer.Option("Hello from 03_Tasks!")) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient() as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await ClientFactory.connect(
                card,
                client_config=ClientConfig(
                    supported_transports=[card.preferred_transport],
                    httpx_client=http,
                ),
            )

            try:
                msg = create_text_message_object(content=text)
                async for reply in client.send_message(msg):
                    print(reply)
                    break
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
