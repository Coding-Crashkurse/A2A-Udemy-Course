import logging
import sys
from pathlib import Path

import uvicorn
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.types import TransportProtocol

# Ensure project root is on sys.path when running as a script from this folder
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.bella_vista import build_agent_card, create_request_handler

HOST = "0.0.0.0"
PORT = 8002


def build_app():
    agent_card = build_agent_card(base_url=f"http://localhost:{PORT}")
    handler = create_request_handler()

    app_builder = A2ARESTFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    return app_builder.build()


app = build_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Starting Bella Vista REST server on %s:%s", HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
