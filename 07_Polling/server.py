import asyncio
import uuid

import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Message,
    Part,
    Role,
    TaskState,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_task

HOST = "localhost"
PORT = 8001


class PollingDemoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # 1/3
        await updater.update_status(
            TaskState.working,
            Message(
                role=Role.agent,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(root=TextPart(text="Working 1/3..."))],
            ),
        )

        await asyncio.sleep(5.0)

        # 2/3
        await updater.update_status(
            TaskState.working,
            Message(
                role=Role.agent,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(root=TextPart(text="Working 2/3..."))],
            ),
        )

        await asyncio.sleep(5.0)

        # 3/3
        await updater.update_status(
            TaskState.working,
            Message(
                role=Role.agent,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(root=TextPart(text="Working 3/3..."))],
            ),
        )

        await asyncio.sleep(5.0)

        # Artifact: Text (für Demo)
        await updater.add_artifact(
            [
                Part(
                    root=TextPart(
                        text="Demo artifact text: Hello from PollingDemoExecutor ✅"
                    )
                )
            ],
            name="result.txt",
        )

        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="Polling Demo Agent (REST)",
    description="Minimal long-running task + polling via GET /v1/tasks/{id}.",
    url=f"http://{HOST}:{PORT}",
    version="0.4.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    additional_interfaces=[],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=PollingDemoExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
