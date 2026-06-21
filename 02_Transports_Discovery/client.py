import asyncio
import logging

import grpc
import httpx
import typer
from a2a.client import ClientConfig, create_client, minimal_agent_card
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_stream_response_text, new_text_message
from a2a.types import AgentCard, Role, SendMessageRequest
from a2a.utils import TransportProtocol

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def load_card(port: int) -> AgentCard:
    base_url = f"http://localhost:{port}"
    try:
        async with httpx.AsyncClient() as http:
            return await A2ACardResolver(http, base_url).get_agent_card()
    except Exception:
        logger.info("No HTTP AgentCard on %s -> assuming gRPC server", base_url)
        return minimal_agent_card(
            url=f"localhost:{port}", transports=[TransportProtocol.GRPC]
        )


async def _run(port: int, text: str) -> None:
    card = await load_card(port)
    iface = card.supported_interfaces[0]
    logger.info("AgentCard: binding=%s url=%s", iface.protocol_binding, iface.url)

    config = ClientConfig(
        supported_protocol_bindings=[
            TransportProtocol.JSONRPC,
            TransportProtocol.HTTP_JSON,
            TransportProtocol.GRPC,
        ],
        grpc_channel_factory=lambda url: grpc.aio.insecure_channel(url),
        httpx_client=httpx.AsyncClient(),
    )
    client = await create_client(card, client_config=config)
    try:
        request = SendMessageRequest(
            message=new_text_message(text=text, role=Role.ROLE_USER)
        )
        async for reply in client.send_message(request):
            logger.info("Reply: %s", get_stream_response_text(reply))
    finally:
        await client.close()


def main(
    port: int = typer.Option(..., help="Agent port on localhost"),
    text: str = typer.Option("Hello!", help="Text to send"),
) -> None:
    asyncio.run(_run(port, text))


if __name__ == "__main__":
    typer.run(main)
