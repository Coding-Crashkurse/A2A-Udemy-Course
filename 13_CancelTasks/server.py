import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Part,
    TaskState,
)
from a2a.utils import TransportProtocol

HOST = "localhost"
PORT = 8001
DURATION_SECONDS = 30

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("13_CancelTask")


class Cancelable30sExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work(
            updater.new_agent_message([Part(text=f"Working... (~{DURATION_SECONDS}s)")])
        )

        await asyncio.sleep(DURATION_SECONDS)

        await updater.add_artifact(
            [Part(text="Result payload (completed)")], name="result.txt"
        )
        await updater.complete(updater.new_agent_message([Part(text="Done")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        log.info("cancel: task_id=%s", context.task_id)
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.update_status(
            TaskState.TASK_STATE_CANCELED,
            updater.new_agent_message([Part(text="Canceled")]),
        )


card = AgentCard(
    name="13 CancelTask Demo Agent (REST)",
    description="Long-running task canceled via CancelTask; the SDK stops execute() for us.",
    version="1.0.0-demo",
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
    agent_executor=Cancelable30sExecutor(),
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
