import argparse
import asyncio
import logging
from typing import Any

import grpc
import httpx
from a2a.client import (
    Client,
    ClientConfig,
    ClientFactory,
    create_text_message_object,
)
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import minimal_agent_card
from a2a.types import AgentCard, Message, Task, TransportProtocol


async def load_card(host: str, port: int) -> AgentCard:
    """Load AgentCard from HTTP; if unavailable, assume a gRPC-only server."""
    base_url = f'http://{host}:{port}'
    try:
        async with httpx.AsyncClient() as client:
            resolver = A2ACardResolver(client, base_url)
            return await resolver.get_agent_card()
    except Exception:
        logging.info(
            'Could not fetch AgentCard via HTTP at %s, assuming gRPC-only server.',
            base_url,
        )
        return minimal_agent_card(
            url=f'{host}:{port}', transports=[TransportProtocol.grpc]
        )


def build_config() -> ClientConfig:
    """Build a ClientConfig that knows all three transports."""
    return ClientConfig(
        supported_transports=[
            TransportProtocol.jsonrpc,
            TransportProtocol.http_json,
            TransportProtocol.grpc,
        ],
        grpc_channel_factory=lambda url: grpc.aio.insecure_channel(url),
        httpx_client=httpx.AsyncClient(),
    )


def _render_reply(reply: Any) -> str:
    if isinstance(reply, Message):
        text_parts = [p.root.text for p in reply.parts if hasattr(p.root, 'text')]
        return f"Message: {' '.join(text_parts)}"
    if isinstance(reply, tuple) and isinstance(reply[0], Task):
        task = reply[0]
        return f'Task {task.id} state={task.status.state}'
    return str(reply)


async def main() -> None:
    parser = argparse.ArgumentParser(description='Simple A2A transport demo client')
    parser.add_argument('--host', default='localhost', help='Host for the agent.')
    parser.add_argument(
        '--port',
        type=int,
        required=True,
        help='Port for the agent (card will be fetched from http://host:port).',
    )
    parser.add_argument('--text', default='Hello from client!', help='Text to send to the agent.')
    parser.add_argument('--task-id', default=None, help='Optional task_id to reuse.')
    parser.add_argument('--context-id', default=None, help='Optional context_id to reuse.')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')

    # Fetch AgentCard (preferred transport comes from the card).
    card = await load_card(args.host, args.port)
    logging.info('Fetched AgentCard: preferred=%s url=%s', card.preferred_transport, card.url)

    client = await ClientFactory.connect(card, client_config=build_config())
    message = create_text_message_object(content=args.text)
    if args.task_id:
        message.task_id = args.task_id
    if args.context_id:
        message.context_id = args.context_id

    try:
        async for reply in client.send_message(message):
            logging.info(_render_reply(reply))
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())
