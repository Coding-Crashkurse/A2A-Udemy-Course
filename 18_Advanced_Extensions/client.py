import asyncio
from uuid import uuid4

import httpx
import typer

from a2a.client import ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard, Message, Part, Role, TextPart, TransportProtocol
from a2a.utils import get_message_text

BASE_URL = "http://localhost:8001"
LANG_EXTENSION_URI = "https://example.com/extensions/language/v1"

app = typer.Typer(add_completion=False)


def print_language_extension_summary(card: AgentCard) -> None:
    ext = next(e for e in (card.capabilities.extensions or []) if e.uri == LANG_EXTENSION_URI)
    params = ext.params or {}
    print(
        f"Language extension: supported={params.get('supportedLanguages')} "
        f"default={params.get('defaultLanguage')}"
    )


def build_message(text: str, language: str) -> Message:
    return Message(
        role=Role.user,
        message_id=str(uuid4()),
        parts=[Part(root=TextPart(text=text))],
        extensions=[LANG_EXTENSION_URI],
        metadata={LANG_EXTENSION_URI: {"language": language}},
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

            client = await ClientFactory.connect(
                card,
                client_config=ClientConfig(
                    supported_transports=[TransportProtocol.http_json],
                    httpx_client=http,
                    streaming=False,
                    polling=False,
                ),
            )

            try:
                msg = build_message(text=text, language=lang)
                it = client.send_message(msg)
                task, _update = await anext(it)
                await it.aclose()

                print(get_message_text(task.status.message))
            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
