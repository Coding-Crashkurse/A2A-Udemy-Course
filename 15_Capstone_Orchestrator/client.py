import asyncio

import httpx
import typer

from a2a.client import ClientConfig, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientFactory
from a2a.types import TransportProtocol
from a2a.utils import get_message_text

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(text: str = typer.Option("Explain the offside rule in soccer briefly.")) -> None:
    async def _run() -> None:
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = ClientFactory(
                ClientConfig(
                    httpx_client=http,
                    supported_transports=[TransportProtocol.http_json],
                    streaming=False,
                    polling=False,
                )
            ).create(card)

            try:
                msg = create_text_message_object(content=text)

                events = client.send_message(msg)
                task, _ = await anext(events)
                async for task, _ in events:
                    pass

                print(get_message_text(task.status.message))
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
