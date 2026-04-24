import asyncio
import json
import uuid
from typing import Literal

import httpx
import typer
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest, Task, TaskState

BASE_URL = "http://localhost:8001"
app = typer.Typer(add_completion=False)

TicketStatus = Literal["open", "closed"]


def get_data_parts(parts):
    out = []
    for p in parts:
        if p.HasField("data"):
            out.append(MessageToDict(p.data))
    return out


def _print_task(task: Task) -> None:
    print(f"taskId={task.id}")
    print(f"contextId={task.context_id}")
    print(f"state={TaskState.Name(task.status.state)}")

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
                data = Struct()
                data.update({"action": "list_tickets", "status": status})

                msg = Message(
                    role=Role.ROLE_USER,
                    message_id=str(uuid.uuid4()),
                    parts=[Part(data=data)],
                )

                request = SendMessageRequest(message=msg)
                async for reply in client.send_message(request):
                    if reply.HasField("task"):
                        _print_task(reply.task)
                        break

            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
