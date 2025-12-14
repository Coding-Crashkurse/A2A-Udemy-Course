import logging
import sys
from pathlib import Path
import uvicorn

from a2a.server.apps import A2AFastAPIApplication
from a2a.types import TransportProtocol

# Ensure project root is on sys.path when running as a script from this folder
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.echo import build_agent_card, create_request_handler

HOST = '0.0.0.0'
PORT = 8000
RPC_URL = '/jsonrpc'


def build_app():
    agent_card = build_agent_card(
        base_url=f'http://localhost:{PORT}{RPC_URL}',
        preferred_transport=TransportProtocol.jsonrpc,
    )
    handler = create_request_handler()
    app_builder = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    return app_builder.build(rpc_url=RPC_URL)


app = build_app()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logging.info('Starting JSON-RPC server on %s:%s', HOST, PORT)
    uvicorn.run(app, host=HOST, port=PORT)
