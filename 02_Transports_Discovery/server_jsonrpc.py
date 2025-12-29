import logging
import uvicorn

from a2a.server.apps import A2AFastAPIApplication
from a2a.types import TransportProtocol

from shared import build_agent_card, create_request_handler

HOST = "0.0.0.0"
PORT = 8000
RPC_URL = "/jsonrpc"


def build_app():
    agent_card = build_agent_card(
        base_url=f"http://localhost:{PORT}{RPC_URL}",
        preferred_transport=TransportProtocol.jsonrpc,
    )
    handler = create_request_handler()
    app_builder = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    return app_builder.build(rpc_url=RPC_URL)


app = build_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Starting JSON-RPC server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
