import asyncio
import logging
import sys
from pathlib import Path

from a2a.server.request_handlers import GrpcHandler
from a2a.types import TransportProtocol

# Ensure project root is on sys.path when running as a script from this folder
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.echo import build_agent_card, create_request_handler

try:
    import grpc
    from a2a.grpc import a2a_pb2_grpc
except ImportError as e:  # pragma: no cover - convenience guard
    raise SystemExit(
        'gRPC dependencies are required. Install with "pip install \"a2a-sdk[grpc]\""'
    ) from e

GRPC_PORT = 50051


async def serve() -> None:
    agent_card = build_agent_card(
        base_url=f'localhost:{GRPC_PORT}',
        preferred_transport=TransportProtocol.grpc,
    )
    handler = create_request_handler()
    grpc_handler = GrpcHandler(agent_card=agent_card, request_handler=handler)

    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(grpc_handler, server)
    server.add_insecure_port(f'[::]:{GRPC_PORT}')

    logging.info('Starting gRPC server on port %s', GRPC_PORT)
    await server.start()
    await server.wait_for_termination()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
