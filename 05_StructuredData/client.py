import asyncio
import json
import uuid
from typing import Literal

import httpx
import typer

from a2a.client import ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import DataPart, Message, Part, Role, Task
from a2a.utils import get_message_text
from a2a.utils.parts import get_data_parts

BASE_URL = "http://localhost:8001"
app = typer.Typer(add_completion=False)

TicketStatus = Literal["open", "closed"]


def _print_task(task: Task) -> None:
    print(f"taskId={task.id}")
    print(f"contextId={task.context_id}")
    print(f"state={task.status.state.value}")

    if task.status.message:
        print("\nstatusMessage.text:")
        print(get_message_text(task.status.message))

        data = get_data_parts(task.status.message.parts)
        if data:
            print("\nstatusMessage.data (DataPart):")
            print(json.dumps(data[0], ensure_ascii=False, indent=2))

    if task.artifacts:
        art = task.artifacts[0]
        art_data = get_data_parts(art.parts)
        if art_data:
            print("\nartifact.data (DataPart):")
            print(json.dumps(art_data[0], ensure_ascii=False, indent=2))


@app.callback(invoke_without_command=True)
def main(
    status: TicketStatus = typer.Option(
        "open", help="Ticket status filter: open|closed"
    ),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await ClientFactory.connect(
                card,
                client_config=ClientConfig(
                    supported_transports=[card.preferred_transport],
                    httpx_client=http,
                ),
            )

            try:
                msg = Message(
                    role=Role.user,
                    message_id=str(uuid.uuid4()),
                    parts=[
                        Part(
                            root=DataPart(
                                data={
                                    "action": "list_tickets",
                                    "status": status,
                                }
                            )
                        )
                    ],
                )

                it = client.send_message(msg)
                task, _update = await anext(it)
                await it.aclose()

                _print_task(task)

            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
