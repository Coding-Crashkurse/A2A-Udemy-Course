import logging

import uvicorn
from fastapi import FastAPI

from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentInterface
from a2a.utils import TransportProtocol

from shared import build_agent_card, create_request_handler

HOST = "0.0.0.0"
PORT = 8000
RPC_URL = "/jsonrpc"


def build_app() -> FastAPI:
    agent_card = build_agent_card(
        AgentInterface(
            url=f"http://localhost:{PORT}{RPC_URL}",
            protocol_binding=TransportProtocol.JSONRPC,
        ),
    )
    handler = create_request_handler(agent_card=agent_card)

    app = FastAPI()
    for route in create_agent_card_routes(agent_card=agent_card):
        app.router.routes.append(route)
    for route in create_jsonrpc_routes(request_handler=handler, rpc_url=RPC_URL):
        app.router.routes.append(route)
    return app


app = build_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Starting JSON-RPC server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
