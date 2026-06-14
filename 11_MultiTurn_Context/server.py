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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("06_MultiTurn")

PHASE_BY_TASK_ID: dict[str, str] = {}


class MultiTurnStreamingExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        is_new_task = context.current_task is None
        task = context.current_task or new_task_from_user_message(context.message)

        if is_new_task:
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        phase = PHASE_BY_TASK_ID.get(task.id)
        log.info(
            "execute task_id=%s context_id=%s is_new=%s phase=%r",
            task.id,
            task.context_id,
            is_new_task,
            phase,
        )

        if phase is None:
            PHASE_BY_TASK_ID[task.id] = "awaiting_name"
            log.info("TURN 1 -> input_required | task_id=%s", task.id)

            await updater.update_status(
                TaskState.TASK_STATE_WORKING,
                updater.new_agent_message(
                    [Part(text="Okay — kurze Rückfrage bevor ich weiter mache…")]
                ),
            )
            await asyncio.sleep(1.0)

            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                updater.new_agent_message([Part(text="Wie heißt du?")]),
            )
            return

        answer = context.get_user_input().strip()
        log.info("TURN 2 -> continue | task_id=%s answer=%r", task.id, answer)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message(
                [Part(text=f"Danke {answer}! Ich mache weiter…")]
            ),
        )
        await asyncio.sleep(1.0)

        await updater.add_artifact(
            [Part(text=f"Hallo {answer}! ✅ (Multi-Turn abgeschlossen)")],
            name="greeting.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(text="Fertig ✅")])
        )

        PHASE_BY_TASK_ID.pop(task.id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="06 Multi-Turn Demo Agent (REST + SSE)",
    description="TASK_STATE_INPUT_REQUIRED + continue same task_id via streaming.",
    version="0.6.1-demo",
    supported_interfaces=[
        AgentInterface(
            url=f"http://{HOST}:{PORT}",
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=MultiTurnStreamingExecutor(),
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
