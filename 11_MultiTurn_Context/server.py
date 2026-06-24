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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("11_MultiTurn")


class MultiTurnExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task

        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)

            updater = TaskUpdater(event_queue, task.id, task.context_id)
            log.info("TURN 1 -> input_required | task_id=%s", task.id)
            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                updater.new_agent_message([Part(text="What's your name?")]),
            )
            return

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        answer = context.get_user_input().strip()
        log.info("TURN 2 -> complete | task_id=%s answer=%r", task.id, answer)

        await updater.add_artifact(
            [Part(text=f"Hello {answer}! (Multi-turn completed)")],
            name="greeting",
        )
        await updater.complete(
            updater.new_agent_message([Part(text=f"Thanks {answer}, done.")])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="11 Multi-Turn Demo Agent (REST, request/response)",
    description="TASK_STATE_INPUT_REQUIRED, then continue the same task_id with a second request.",
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
    agent_executor=MultiTurnExecutor(),
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
