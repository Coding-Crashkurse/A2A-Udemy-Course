import asyncio
import logging

from a2a.server.request_handlers import GrpcHandler
from a2a.types import TransportProtocol

from .shared import build_agent_card, create_request_handler

try:
    import grpc
    from a2a.grpc import a2a_pb2_grpc
except ImportError as e:
    raise SystemExit(
        'gRPC dependencies are required. Install with: pip install "a2a-sdk[grpc]"'
    ) from e

GRPC_PORT = 50051


async def serve() -> None:
    agent_card = build_agent_card(
        base_url=f"localhost:{GRPC_PORT}",
        preferred_transport=TransportProtocol.grpc,
    )
    handler = create_request_handler()
    grpc_handler = GrpcHandler(agent_card=agent_card, request_handler=handler)

    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(grpc_handler, server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")

    logging.info("Starting gRPC server on port %s", GRPC_PORT)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(serve())
