import asyncio

import httpx
import typer

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest
from a2a.utils import TransportProtocol

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(text: str = typer.Option("Explain the offside rule in soccer briefly.")) -> None:
    async def _run() -> None:
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await create_client(
                card,
                client_config=ClientConfig(
                    httpx_client=http,
                    supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
                    streaming=False,
                    polling=False,
                ),
            )

            try:
                request = SendMessageRequest(
                    message=new_text_message(text=text, role=Role.ROLE_USER)
                )
                last_text = ""
                async for reply in client.send_message(request):
                    if reply.HasField("task"):
                        if reply.task.status.HasField("message"):
                            last_text = get_message_text(reply.task.status.message)
                    elif reply.HasField("status_update"):
                        if reply.status_update.status.HasField("message"):
                            last_text = get_message_text(
                                reply.status_update.status.message
                            )

                print(last_text)
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
