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
    InvalidParamsError,
    Part,
    TaskState,
)
from a2a.utils import TransportProtocol

try:
    from a2a.types import TaskNotCancelableError
except Exception:
    TaskNotCancelableError = None

HOST = "localhost"
PORT = 8001
DURATION_SECONDS = 30

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("10_CancelTask")

CANCEL_EVENT_BY_TASK_ID: dict[str, asyncio.Event] = {}


def _raise_not_cancelable(msg: str) -> None:
    if TaskNotCancelableError is not None:
        raise TaskNotCancelableError(message=msg)
    raise InvalidParamsError(message=msg)


class Cancelable30sExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)

        cancel_ev = CANCEL_EVENT_BY_TASK_ID.get(task.id)
        if cancel_ev is None:
            cancel_ev = asyncio.Event()
            CANCEL_EVENT_BY_TASK_ID[task.id] = cancel_ev

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message(
                [Part(text="Accepted. Working... (~30s)")]
            ),
        )

        for sec in range(1, DURATION_SECONDS + 1):
            await asyncio.sleep(1.0)

            if cancel_ev.is_set():
                log.info(
                    "execute: task_id=%s observed cancel flag at t=%ss", task.id, sec
                )
                await updater.update_status(
                    TaskState.TASK_STATE_CANCELED,
                    updater.new_agent_message([Part(text="Canceled ✅")]),
                )
                CANCEL_EVENT_BY_TASK_ID.pop(task.id, None)
                return

            if sec % 5 == 0:
                await updater.update_status(
                    TaskState.TASK_STATE_WORKING,
                    updater.new_agent_message(
                        [Part(text=f"Progress: {sec}/{DURATION_SECONDS}s")]
                    ),
                )

        await updater.add_artifact(
            [Part(text="Result payload (completed)")],
            name="result.txt",
        )
        await updater.complete(
            updater.new_agent_message([Part(text="Done ✅")])
        )

        CANCEL_EVENT_BY_TASK_ID.pop(task.id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        if not task_id:
            raise InvalidParamsError(message="missing task id")

        task = context.current_task
        if task is None:
            raise InvalidParamsError(message="task not found")

        state = task.status.state if task.status else None
        log.info("cancel: task_id=%s state=%s", task_id, TaskState.Name(state) if state else None)

        if state in {
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_REJECTED,
            TaskState.TASK_STATE_CANCELED,
        }:
            _raise_not_cancelable(
                f"Task cannot be canceled - current state: {TaskState.Name(state)}"
            )

        ev = CANCEL_EVENT_BY_TASK_ID.get(task_id)
        if ev is None:
            ev = asyncio.Event()
            CANCEL_EVENT_BY_TASK_ID[task_id] = ev
        ev.set()

        updater = TaskUpdater(event_queue, task_id, task.context_id)
        await updater.update_status(
            TaskState.TASK_STATE_CANCELED,
            updater.new_agent_message([Part(text="Canceled ✅")]),
        )


card = AgentCard(
    name="10 CancelTask Demo Agent (REST)",
    description="Cancelable long-running task + CancelTask semantics (best effort).",
    version="0.10.0-demo",
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
