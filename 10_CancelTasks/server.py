import asyncio
import logging

import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_task
from a2a.utils.errors import ServerError

# Optional je nach SDK-Version
try:
    from a2a.types import TaskNotCancelableError  # type: ignore
except Exception:  # pragma: no cover
    TaskNotCancelableError = None  # type: ignore

HOST = "localhost"
PORT = 8001
DURATION_SECONDS = 30

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("10_CancelTask")

# Cooperative cancellation flag pro Task
CANCEL_EVENT_BY_TASK_ID: dict[str, asyncio.Event] = {}


def _raise_not_cancelable(msg: str) -> None:
    """
    Spec-konform: TaskNotCancelableError, falls im SDK vorhanden.
    Fallback: InvalidParamsError.
    """
    if TaskNotCancelableError is not None:
        raise ServerError(TaskNotCancelableError(message=msg))  # type: ignore
    raise ServerError(InvalidParamsError(message=msg))


class Cancelable30sExecutor(AgentExecutor):
    """
    Long-running task (~30s), cancelable (best effort).
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)

        cancel_ev = CANCEL_EVENT_BY_TASK_ID.get(task.id)
        if cancel_ev is None:
            cancel_ev = asyncio.Event()
            CANCEL_EVENT_BY_TASK_ID[task.id] = cancel_ev

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message(
                [Part(root=TextPart(text="Accepted. Working... (~30s)"))]
            ),
        )

        # Work loop: jede Sekunde cancel check, alle 5s progress update
        for sec in range(1, DURATION_SECONDS + 1):
            await asyncio.sleep(1.0)

            if cancel_ev.is_set():
                log.info("execute: task_id=%s observed cancel flag at t=%ss", task.id, sec)
                await updater.update_status(
                    TaskState.canceled,
                    updater.new_agent_message([Part(root=TextPart(text="Canceled ✅"))]),
                )
                CANCEL_EVENT_BY_TASK_ID.pop(task.id, None)
                return

            if sec % 5 == 0:
                await updater.update_status(
                    TaskState.working,
                    updater.new_agent_message(
                        [Part(root=TextPart(text=f"Progress: {sec}/{DURATION_SECONDS}s"))]
                    ),
                )

        # completion
        await updater.add_artifact(
            [Part(root=TextPart(text="Result payload (completed)"))],
            name="result.txt",
        )
        await updater.complete(
            updater.new_agent_message([Part(root=TextPart(text="Done ✅"))])
        )

        CANCEL_EVENT_BY_TASK_ID.pop(task.id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Wird vom Server bei /v1/tasks/{id}:cancel aufgerufen.

        Spec: Cancel ist best-effort. Wenn Task schon terminal ist
        (completed/failed/rejected/canceled), darf TaskNotCancelableError kommen.
        """
        task_id = context.task_id
        if not task_id:
            raise ServerError(InvalidParamsError(message="missing task id"))

        task = context.current_task
        if task is None:
            raise ServerError(InvalidParamsError(message="task not found"))

        state = task.status.state if task.status else None
        log.info("cancel: task_id=%s state=%s", task_id, getattr(state, "value", state))

        if state in {TaskState.completed, TaskState.failed, TaskState.rejected, TaskState.canceled}:
            _raise_not_cancelable(f"Task cannot be canceled - current state: {state}")

        # best-effort cooperative cancellation
        ev = CANCEL_EVENT_BY_TASK_ID.get(task_id)
        if ev is None:
            ev = asyncio.Event()
            CANCEL_EVENT_BY_TASK_ID[task_id] = ev
        ev.set()

        # Update state sofort auf canceled, damit GET /v1/tasks es sofort sieht
        updater = TaskUpdater(event_queue, task_id, task.context_id)
        await updater.update_status(
            TaskState.canceled,
            updater.new_agent_message([Part(root=TextPart(text="Canceled ✅"))]),
        )


card = AgentCard(
    name="10 CancelTask Demo Agent (REST)",
    description="Cancelable long-running task + CancelTask semantics (best effort).",
    url=f"http://{HOST}:{PORT}",
    version="0.10.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    additional_interfaces=[],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=Cancelable30sExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
