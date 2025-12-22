import logging
import uvicorn

from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.types import TransportProtocol

from shared import build_agent_card, create_request_handler

HOST = "0.0.0.0"
PORT = 8001


def build_app():
    agent_card = build_agent_card(
        base_url=f"http://localhost:{PORT}",
        preferred_transport=TransportProtocol.http_json,
    )
    handler = create_request_handler()
    app_builder = A2ARESTFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    return app_builder.build()


app = build_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Starting REST server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
