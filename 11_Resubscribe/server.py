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
    Part,
    TaskState,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_task

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

TOTAL_SECONDS = 30
TICK_SECONDS = 1

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("11_SubscribeToTask")


class LongRunningStreamingExecutor(AgentExecutor):
    """
    Creates a long-running task (~30s) and emits frequent status updates.
    This is perfect to demo:
      1) message:stream (start + stream)
      2) connection drop
      3) resubscribe (SubscribeToTask) to continue streaming updates
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)

        # Initial snapshot (submitted)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        log.info("execute task_id=%s context_id=%s", task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message(
                [Part(root=TextPart(text="Accepted. Working... (~30s)"))]
            ),
        )

        # Progress loop
        elapsed = 0
        while elapsed < TOTAL_SECONDS:
            await asyncio.sleep(TICK_SECONDS)
            elapsed += TICK_SECONDS

            await updater.update_status(
                TaskState.working,
                updater.new_agent_message(
                    [Part(root=TextPart(text=f"Progress: {elapsed}/{TOTAL_SECONDS}s"))]
                ),
            )

        # Artifact
        await updater.add_artifact(
            [Part(root=TextPart(text="Result payload for SubscribeToTask demo ✅"))],
            name="result.txt",
        )

        # Complete
        await updater.complete(
            updater.new_agent_message([Part(root=TextPart(text="Done ✅"))])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Optional: you can implement cancel semantics here,
        # but it's not required for SubscribeToTask demo.
        return


card = AgentCard(
    name="11 SubscribeToTask Demo Agent (REST + SSE)",
    description="Long-running streaming task + resubscribe support (SubscribeToTask).",
    url=BASE_URL,
    version="0.11.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    additional_interfaces=[],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=LongRunningStreamingExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
