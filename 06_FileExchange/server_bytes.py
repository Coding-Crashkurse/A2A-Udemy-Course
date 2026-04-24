import uuid
from dataclasses import dataclass

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
        if p.HasField("raw") or p.HasField("url"):
            return p
    raise ValueError("no file part found")


class BytesUploadExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        file_in = _first_file_part(context.message.parts)
        raw = file_in.raw
        store.content = update_text(raw)

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
    name="06 FileExchange Bytes (REST)",
    description="Client sends file bytes, agent returns file URI for download.",
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
    agent_executor=BytesUploadExecutor(),
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
