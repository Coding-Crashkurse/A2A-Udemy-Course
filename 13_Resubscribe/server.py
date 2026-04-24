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
BASE_URL = f"http://{HOST}:{PORT}"

TOTAL_SECONDS = 30
TICK_SECONDS = 1

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("11_SubscribeToTask")


class LongRunningStreamingExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)

        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        log.info("execute task_id=%s context_id=%s", task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message(
                [Part(text="Accepted. Working... (~30s)")]
            ),
        )

        elapsed = 0
        while elapsed < TOTAL_SECONDS:
            await asyncio.sleep(TICK_SECONDS)
            elapsed += TICK_SECONDS

            await updater.update_status(
                TaskState.TASK_STATE_WORKING,
                updater.new_agent_message(
                    [Part(text=f"Progress: {elapsed}/{TOTAL_SECONDS}s")]
                ),
            )

        await updater.add_artifact(
            [Part(text="Result payload for SubscribeToTask demo ✅")],
            name="result.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(text="Done ✅")])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="11 SubscribeToTask Demo Agent (REST + SSE)",
    description="Long-running streaming task + resubscribe support (SubscribeToTask).",
    version="0.11.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=BASE_URL,
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=LongRunningStreamingExecutor(),
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
