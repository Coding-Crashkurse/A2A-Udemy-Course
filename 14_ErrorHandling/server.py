"""Minimal A2A error-handling demo server.

Goal of this chapter: show the *error model*. A2A defines a fixed catalog of
errors, and each one maps consistently onto every transport (a JSON-RPC code,
an HTTP status, a gRPC status). This server is deliberately tiny — its only job
is to let the client provoke a few of those errors at the protocol boundary:

  * GET an unknown task            -> TaskNotFoundError      (404 / -32001)
  * cancel an already-finished task -> TaskNotCancelableError (409 / -32002)
  * call message:stream here        -> UnsupportedOperationError (400 / -32004)
    (the agent advertises streaming=False, so the SDK rejects it)

NOTE (important detail): an exception raised *inside* execute() does NOT become
a protocol error — the SDK turns it into a FAILED task (HTTP 200). Protocol
errors come from the handler boundary (get_task / cancel / capability checks),
which is exactly what we trigger here.
"""

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

# The error catalog + its transport mappings live in the SDK. We import them so
# we can print the mapping table — this is the "Spec 5.4" table from the slides.
from a2a.utils.errors import (
    A2A_REST_ERROR_MAPPING,
    JSON_RPC_ERROR_CODE_MAP,
    TaskNotCancelableError,
)

HOST = "localhost"
PORT = 8014

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("11_ErrorHandling")

TERMINAL_STATES = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_REJECTED,
    TaskState.TASK_STATE_CANCELED,
}


class QuickExecutor(AgentExecutor):
    """Creates a task and completes it immediately, so the client has a
    terminal task to (illegally) try to cancel afterwards."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working...")]),
        )
        await updater.add_artifact([Part(text="Result payload")], name="result.txt")
        await updater.complete(updater.new_agent_message([Part(text="Done ✅")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Cancellation is best-effort. A task that already reached a terminal
        # state cannot be canceled -> raise the catalog error that maps to 409.
        task = context.current_task
        if task is None:
            raise InvalidParamsError(message="task not found")

        state = task.status.state if task.status else None
        if state in TERMINAL_STATES:
            raise TaskNotCancelableError(
                message=f"Task cannot be canceled - state={TaskState.Name(state)}"
            )

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(
            TaskState.TASK_STATE_CANCELED,
            updater.new_agent_message([Part(text="Canceled ✅")]),
        )


card = AgentCard(
    name="11 Error Handling Demo Agent (REST)",
    description="Tiny agent used to provoke and inspect the A2A error model.",
    version="0.11.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=f"http://{HOST}:{PORT}",
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    # streaming=False on purpose: calling message:stream becomes an
    # UnsupportedOperationError (the SDK's @validate guard rejects it).
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=QuickExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)


def _print_error_catalog() -> None:
    """Log the A2A error catalog: one error -> three transport representations."""
    log.info("A2A error catalog (error  ->  HTTP / JSON-RPC / gRPC):")
    for err_cls, rest in A2A_REST_ERROR_MAPPING.items():
        jsonrpc = JSON_RPC_ERROR_CODE_MAP.get(err_cls, "?")
        log.info(
            "  %-34s HTTP %-3d | JSON-RPC %-7s | gRPC %s",
            err_cls.__name__,
            rest.http_code,
            jsonrpc,
            rest.grpc_status,
        )


if __name__ == "__main__":
    _print_error_catalog()
    uvicorn.run(app, host=HOST, port=PORT)
