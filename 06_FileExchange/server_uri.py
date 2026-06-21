import ipaddress
import logging
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Artifact,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils import TransportProtocol

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"


@dataclass(slots=True)
class DownloadStore:
    content: bytes


store = DownloadStore(content=b"")


def update_text(raw: bytes) -> bytes:
    return raw + b"\nI was updated\n"


def _first_file_part(parts):
    for p in parts:
        if p.HasField("url") or p.HasField("raw"):
            return p
    raise ValueError("no file part found")


log = logging.getLogger("06_FileExchange")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# A server that fetches a client-supplied URL is a classic SSRF vector: a caller
# could aim it at internal services (cloud metadata, admin ports, databases…).
# Always validate the destination BEFORE fetching. This demo pulls from a local
# file server, so we only *warn* on internal targets — set ENFORCE_SSRF_GUARD to
# True to reject them the way a production agent must.
ENFORCE_SSRF_GUARD = False


def validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"SSRF guard: refused non-http(s) scheme {parsed.scheme!r}")

    host = parsed.hostname or ""
    internal = host == "localhost"
    try:
        ip = ipaddress.ip_address(host)
        internal = ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
    except ValueError:
        pass  # a hostname, not a literal IP — a real guard resolves DNS, re-checks

    if internal:
        msg = f"SSRF guard: client URL targets an internal host ({host!r})"
        if ENFORCE_SSRF_GUARD:
            raise ValueError(msg)
        log.warning("%s - allowed only because this is a localhost demo", msg)


class UriUploadExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        file_in = _first_file_part(context.message.parts)

        # SECURITY: validate the client-supplied URL before fetching it (SSRF).
        validate_fetch_url(file_in.url)

        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(file_in.url)
            r.raise_for_status()
            store.content = update_text(r.content)

        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="download.txt",
            parts=[
                Part(
                    url=f"{BASE_URL}/download.txt",
                    filename="download.txt",
                    media_type="text/plain",
                )
            ],
        )

        done_msg = new_text_message(
            text="Done.",
            context_id=context.context_id,
            task_id=context.task_id,
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=done_msg),
            history=[context.message, done_msg],
            artifacts=[artifact],
        )

        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="06 FileExchange URI Fetch (REST)",
    description="Client sends file URI, agent fetches and returns file URI for download.",
    version="0.6.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=BASE_URL,
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=UriUploadExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)


@app.get("/download.txt")
async def download() -> Response:
    return Response(
        content=store.content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="download.txt"'},
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
