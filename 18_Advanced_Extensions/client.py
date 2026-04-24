import asyncio
from uuid import uuid4

import httpx
import typer
from google.protobuf.struct_pb2 import Struct

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest
from a2a.utils import TransportProtocol

BASE_URL = "http://localhost:8001"
LANG_EXTENSION_URI = "https://example.com/extensions/language/v1"

app = typer.Typer(add_completion=False)


def print_language_extension_summary(card: AgentCard) -> None:
    ext = next(
        e for e in (card.capabilities.extensions or []) if e.uri == LANG_EXTENSION_URI
    )
    params = {}
    if ext.HasField("params"):
        from google.protobuf.json_format import MessageToDict
        params = MessageToDict(ext.params)
    print(
        f"Language extension: supported={params.get('supportedLanguages')} "
        f"default={params.get('defaultLanguage')}"
    )


def build_message(text: str, language: str) -> Message:
    metadata = Struct()
    metadata.update({LANG_EXTENSION_URI: {"language": language}})
    return Message(
        role=Role.ROLE_USER,
        message_id=str(uuid4()),
        parts=[Part(text=text)],
        extensions=[LANG_EXTENSION_URI],
        metadata=metadata,
    )


@app.callback(invoke_without_command=True)
def main(
    lang: str = typer.Option("en", help="en|de|es"),
    text: str = typer.Option(..., "--text", help="Prompt that will be sent to the LLM"),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()
            print_language_extension_summary(card)

            client = await create_client(
                card,
                client_config=ClientConfig(
                    supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
                    httpx_client=http,
                    streaming=False,
                    polling=False,
                ),
            )

            try:
                msg = build_message(text=text, language=lang)
                request = SendMessageRequest(message=msg)
                async for reply in client.send_message(request):
                    if reply.HasField("task"):
                        if reply.task.status.HasField("message"):
                            print(get_message_text(reply.task.status.message))
                        break
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
