from __future__ import annotations

import asyncio

import httpx
import typer

from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import Task
from a2a.utils import get_message_text

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(text: str = typer.Option("Erklär mir Abseits im Fußball kurz.")) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient() as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await ClientFactory.connect(
                card,
                client_config=ClientConfig(
                    streaming=False,  # Orchestrator selbst streamt nicht
                    polling=False,
                    supported_transports=[card.preferred_transport],
                    httpx_client=http,
                ),
            )

            try:
                msg = create_text_message_object(content=text)

                last_task: Task | None = None
                async for ev in client.send_message(msg):
                    if isinstance(ev, tuple):
                        task, _update = ev
                        last_task = task

                if last_task is None or last_task.status.message is None:
                    print("(no task message)")
                    return

                print(get_message_text(last_task.status.message))
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
