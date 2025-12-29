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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("06_MultiTurn")

# Global, damit es auch funktioniert, wenn der Executor pro Request neu erstellt wird
PHASE_BY_TASK_ID: dict[str, str] = {}


class MultiTurnStreamingExecutor(AgentExecutor):
    """
    Multi-Turn Demo (Streaming):

    Turn 1:
      - working
      - input_required ("Wie heißt du?")

    Turn 2 (same task_id):
      - working
      - artifact
      - completed
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        is_new_task = context.current_task is None
        task = context.current_task or new_task(context.message)

        # WICHTIG:
        # Nur beim neuen Task einen initialen Snapshot enqueuen.
        # Sonst startet Turn 2 wieder mit dem alten Snapshot (input_required),
        # und viele Clients beenden dann den Stream früh.
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
            # ---- TURN 1 ----
            PHASE_BY_TASK_ID[task.id] = "awaiting_name"
            log.info("TURN 1 -> input_required | task_id=%s", task.id)

            await updater.update_status(
                TaskState.working,
                updater.new_agent_message(
                    [Part(root=TextPart(text="Okay — kurze Rückfrage bevor ich weiter mache…"))]
                ),
            )
            await asyncio.sleep(1.0)

            await updater.update_status(
                TaskState.input_required,
                updater.new_agent_message([Part(root=TextPart(text="Wie heißt du?"))]),
            )
            return

        # ---- TURN 2 ----
        answer = context.get_user_input().strip()
        log.info("TURN 2 -> continue | task_id=%s answer=%r", task.id, answer)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text=f"Danke {answer}! Ich mache weiter…"))]),
        )
        await asyncio.sleep(1.0)

        await updater.add_artifact(
            [Part(root=TextPart(text=f"Hallo {answer}! ✅ (Multi-Turn abgeschlossen)"))],
            name="greeting.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(root=TextPart(text="Fertig ✅"))])
        )

        # cleanup
        PHASE_BY_TASK_ID.pop(task.id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="06 Multi-Turn Demo Agent (REST + SSE)",
    description="TASK_STATE_INPUT_REQUIRED + continue same task_id via streaming.",
    url=f"http://{HOST}:{PORT}",
    version="0.6.1-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    additional_interfaces=[],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=MultiTurnStreamingExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
