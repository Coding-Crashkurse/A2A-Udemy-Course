import uuid
from dataclasses import dataclass

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Artifact,
    FilePart,
    FileWithUri,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TransportProtocol,
)
from a2a.utils import new_agent_text_message
from a2a.utils.parts import get_file_parts

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"


@dataclass(slots=True)
class DownloadStore:
    content: bytes


store = DownloadStore(content=b"")


def update_text(raw: bytes) -> bytes:
    return raw + b"\nI was updated\n"


class UriUploadExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        file_in = get_file_parts(context.message.parts)[0]
        file_in = FileWithUri(**file_in.model_dump())

        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(file_in.uri)
            r.raise_for_status()
            store.content = update_text(r.content)

        file_out = FileWithUri(
            uri=f"{BASE_URL}/download.txt",
            name="download.txt",
            mime_type="text/plain",
        )

        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="download.txt",
            parts=[Part(root=FilePart(file=file_out))],
        )

        done_msg = new_agent_text_message(
            "Done.",
            context_id=context.context_id,
            task_id=context.task_id,
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.completed, message=done_msg),
            history=[context.message, done_msg],
            artifacts=[artifact],
        )

        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="06 FileExchange URI Fetch (REST)",
    description="Client sends fileWithUri, agent fetches and returns fileWithUri for download.",
    url=BASE_URL,
    version="0.6.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=UriUploadExecutor(),
    task_store=InMemoryTaskStore(),
)

app: FastAPI = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()


@app.get("/download.txt")
async def download() -> Response:
    return Response(
        content=store.content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="download.txt"'},
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
