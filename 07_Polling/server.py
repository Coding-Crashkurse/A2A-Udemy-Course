import asyncio
import uuid

import uvicorn
from fastapi import FastAPI

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Message,
    Part,
    Role,
    TaskState,
)
from a2a.utils import TransportProtocol
from a2a.helpers import new_task_from_user_message

HOST = "localhost"
PORT = 8001


class PollingDemoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            Message(
                role=Role.ROLE_AGENT,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(text="Working 1/3...")],
            ),
        )

        await asyncio.sleep(5.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            Message(
                role=Role.ROLE_AGENT,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(text="Working 2/3...")],
            ),
        )

        await asyncio.sleep(5.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            Message(
                role=Role.ROLE_AGENT,
                message_id=str(uuid.uuid4()),
                context_id=task.context_id,
                task_id=task.id,
                parts=[Part(text="Working 3/3...")],
            ),
        )

        await asyncio.sleep(5.0)

        await updater.add_artifact(
            [Part(text="Demo artifact text: Hello from PollingDemoExecutor ✅")],
            name="result.txt",
        )

        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="Polling Demo Agent (REST)",
    description="Minimal long-running task + polling via GET /v1/tasks/{id}.",
    version="0.4.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=f"http://{HOST}:{PORT}",
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=PollingDemoExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
