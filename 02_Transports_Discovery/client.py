import asyncio
import logging

import grpc
import httpx
import typer
from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import minimal_agent_card
from a2a.types import AgentCard, Message, TransportProtocol

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def load_card(port: int) -> AgentCard:
    base_url = f"http://localhost:{port}"
    try:
        async with httpx.AsyncClient() as http:
            return await A2ACardResolver(http, base_url).get_agent_card()
    except Exception:
        logger.info("No HTTP AgentCard on %s -> assuming gRPC server", base_url)
        return minimal_agent_card(url=f"localhost:{port}", transports=[TransportProtocol.grpc])


def build_config() -> ClientConfig:
    return ClientConfig(
        supported_transports=[
            TransportProtocol.jsonrpc,
            TransportProtocol.http_json,
            TransportProtocol.grpc,
        ],
        grpc_channel_factory=lambda url: grpc.aio.insecure_channel(url),
        httpx_client=httpx.AsyncClient(),
    )


def message_to_text(msg: Message) -> str:
    parts: list[str] = []
    for p in msg.parts:
        root = getattr(p, "root", None)
        txt = getattr(root, "text", None)
        if txt:
            parts.append(txt)
    return " ".join(parts).strip()


async def _run(port: int, text: str) -> None:
    card = await load_card(port)
    logger.info("AgentCard: preferred=%s url=%s", card.preferred_transport, card.url)

    client = await ClientFactory.connect(card, client_config=build_config())
    try:
        msg = create_text_message_object(content=text)
        async for reply in client.send_message(msg):
            if isinstance(reply, Message):
                logger.info("Reply: %s", message_to_text(reply))
            else:
                logger.info("Reply: %r", reply)
    finally:
        await client.close()


def main(
    port: int = typer.Option(..., help="Agent port on localhost"),
    text: str = typer.Option("Hello!", help="Text to send"),
) -> None:
    asyncio.run(_run(port, text))


if __name__ == "__main__":
    typer.run(main)
