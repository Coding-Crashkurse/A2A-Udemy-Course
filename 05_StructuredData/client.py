import asyncio
import json
import uuid

import httpx
import typer
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Value

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import Message, Part, Role, SendMessageRequest

BASE_URL = "http://localhost:8001"
app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def main(
    status: str = typer.Option("open", help="Ticket status filter: open|closed"),
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
                data = Value()
                data.struct_value.update({"action": "list_tickets", "status": status})
                request = SendMessageRequest(
                    message=Message(
                        role=Role.ROLE_USER,
                        message_id=str(uuid.uuid4()),
                        parts=[Part(data=data)],
                    )
                )
                async for reply in client.send_message(request):
                    if reply.HasField("task"):
                        for p in reply.task.status.message.parts:
                            if p.HasField("data"):
                                print(json.dumps(MessageToDict(p.data), ensure_ascii=False, indent=2))
                        break
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
