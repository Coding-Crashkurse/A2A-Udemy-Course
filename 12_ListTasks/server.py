import logging
import random

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
)
from a2a.utils import TransportProtocol

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

FAIL_PROBABILITY = 0.3

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("12_ListTasks")


class RandomOutcomeExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work(updater.new_agent_message([Part(text="Working...")]))

        user_text = context.get_user_input()

        if random.random() < FAIL_PROBABILITY:
            log.info("FAILED   | task_id=%s", task.id)
            await updater.failed(
                updater.new_agent_message([Part(text=f"Failed (random): {user_text}")])
            )
            return

        log.info("COMPLETED | task_id=%s", task.id)
        await updater.add_artifact([Part(text=f"Echo: {user_text}")], name="result")
        await updater.complete(updater.new_agent_message([Part(text="Done.")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="12 ListTasks Demo Agent (REST)",
    description="Request/response agent whose tasks randomly complete or fail, listable via ListTasks.",
    version="1.0.0-demo",
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
    agent_executor=RandomOutcomeExecutor(),
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
