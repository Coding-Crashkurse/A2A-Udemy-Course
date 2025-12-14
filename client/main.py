import asyncio
import logging
from typing import Any

import httpx
import typer
from a2a.client import (
    Client,
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import minimal_agent_card
from a2a.types import (
    AgentCard,
    Message,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TransportProtocol,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def load_agent_card(host: str, port: int) -> AgentCard:
    """
    Fetch AgentCard via HTTP.
    REST-only: Wenn das fehlschlägt, fallback auf minimal HTTP+JSON card.
    """
    base_url = f"http://{host}:{port}"
    try:
        async with httpx.AsyncClient() as client:
            resolver = A2ACardResolver(client, base_url)
            return await resolver.get_agent_card()
    except Exception as e:
        logger.info("Could not fetch AgentCard from %s (%s). Falling back to minimal REST card.", base_url, e)
        return minimal_agent_card(
            url=base_url,
            transports=[TransportProtocol.http_json],
        )


def build_config() -> ClientConfig:
    """
    Tasks Basics ohne Streaming:
    - streaming=False
    - polling=True  (Client holt Task-Updates über GetTask/Polling)
    """
    return ClientConfig(
        supported_transports=[TransportProtocol.http_json],
        httpx_client=httpx.AsyncClient(),
        extensions=None,
        streaming=False,
        polling=True,
    )


def _message_to_text(msg: Message) -> str:
    text_parts = []
    for p in msg.parts:
        root = getattr(p, "root", None)
        txt = getattr(root, "text", None)
        if txt:
            text_parts.append(txt)
    return " ".join(text_parts).strip()


def render_reply(reply: Any) -> str:
    # Message-only
    if isinstance(reply, Message):
        return f"Message: {_message_to_text(reply)}"

    # Task-based: tuple[Task, TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None]
    if isinstance(reply, tuple) and len(reply) == 2 and isinstance(reply[0], Task):
        task, event = reply
        base = f"Task {task.id} [state={task.status.state}] (context={task.context_id})"

        if event is None:
            return base + " -> initial response"

        if isinstance(event, TaskStatusUpdateEvent):
            status_msg = ""
            if event.status and event.status.message:
                status_msg = _message_to_text(event.status.message)
            tail = f"status_update state={event.status.state} final={event.final}"
            if status_msg:
                tail += f" msg={status_msg!r}"
            return base + " -> " + tail

        if isinstance(event, TaskArtifactUpdateEvent):
            artifact_texts = []
            if event.artifact and event.artifact.parts:
                for part in event.artifact.parts:
                    root = getattr(part, "root", None)
                    txt = getattr(root, "text", None)
                    if txt:
                        artifact_texts.append(txt)
            text = "\n".join(artifact_texts).strip()
            return base + f" -> artifact_update last_chunk={event.last_chunk}:\n{text}"

        return base + f" -> update={type(event).__name__}"

    return str(reply)


async def run_client(
    host: str,
    port: int,
    text: str,
    task_id: str | None,
    context_id: str | None,
) -> None:
    card = await load_agent_card(host, port)
    logger.info("AgentCard loaded. Preferred Transport: %s | url=%s", card.preferred_transport, card.url)

    client: Client = await ClientFactory.connect(
        card,
        client_config=build_config(),
    )

    message = create_text_message_object(content=text)
    if task_id:
        message.task_id = task_id
    if context_id:
        message.context_id = context_id

    try:
        async for reply in client.send_message(message):
            logger.info("\n%s", render_reply(reply))
    finally:
        await client.close()


def main(
    text: str = typer.Option("Wie sind die Öffnungszeiten vom Bella Vista?", help="Text to send to the agent"),
    host: str = typer.Option("localhost", help="Agent host"),
    port: int = typer.Option(..., help="Agent port (required)"),
    task_id: str | None = typer.Option(None, help="Optional task_id to reuse"),
    context_id: str | None = typer.Option(None, help="Optional context_id to reuse"),
) -> None:
    asyncio.run(run_client(host, port, text, task_id, context_id))


if __name__ == "__main__":
    typer.run(main)
