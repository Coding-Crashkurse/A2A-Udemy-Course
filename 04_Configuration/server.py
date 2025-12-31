import asyncio
import logging
import uuid

import typer
import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    Artifact,
    InvalidParamsError,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_agent_text_message
from a2a.utils.errors import ServerError
from a2a.utils.task import apply_history_length as apply_history_length_task

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

app = typer.Typer(add_completion=False)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("04_Configuration")


class ConfigurationDemoExecutor(AgentExecutor):
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ServerError(InvalidParamsError(message="missing message"))

        cfg = context.configuration
        blocking = bool(cfg.blocking) if cfg and cfg.blocking is not None else False
        history_length = cfg.history_length if cfg else None
        if history_length is not None and history_length < 0:
            raise ServerError(InvalidParamsError(message="historyLength must be >= 0"))

        user_text = context.get_user_input()

        log.info(
            "task_id=%s context_id=%s blocking=%s history_length=%r",
            context.task_id,
            context.context_id,
            blocking,
            history_length,
        )

        # 1) Immer zuerst "working" Event
        started_msg = new_agent_text_message(
            "Working… (step 1/2)",
            context_id=context.context_id,
            task_id=context.task_id,
        )
        initial_history_full = [context.message, started_msg]

        initial_task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.working, message=started_msg),
            history=initial_history_full,
            artifacts=[],
            metadata={
                "section": "04_Configuration",
                "phase": "initial",
                "blocking": blocking,
                "history_length": history_length,
            },
        )
        initial_task = apply_history_length_task(initial_task, history_length)
        await event_queue.enqueue_event(initial_task)

        # 2) Simulierter Workload
        await asyncio.sleep(self.delay_seconds)

        # 3) Finaler Task
        done_msg = new_agent_text_message(
            f"Done ✅ Echo: {user_text}",
            context_id=context.context_id,
            task_id=context.task_id,
        )

        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="result.txt",
            description="Text artifact (demo).",
            parts=[Part(root=TextPart(text=f"Echo: {user_text}"))],
            metadata={"media_type": "text/plain"},
        )

        final_history_full = [context.message, started_msg, done_msg]
        final_task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.completed, message=done_msg),
            history=final_history_full,
            artifacts=[artifact],
            metadata={
                "section": "04_Configuration",
                "phase": "final",
                "blocking": blocking,
                "history_length": history_length,
            },
        )
        final_task = apply_history_length_task(final_task, history_length)
        await event_queue.enqueue_event(final_task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


@app.callback(invoke_without_command=True)
def main(
    delay: float = typer.Option(2.5, help="Simulated work duration (seconds)"),
) -> None:
    card = AgentCard(
        name="04_Configuration Demo Agent (REST)",
        description="Shows blocking + historyLength.",
        version="0.4.0-demo",
        protocol_version="0.3.0",
        url=BASE_URL,
        preferred_transport=TransportProtocol.http_json,
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )

    handler = DefaultRequestHandler(
        agent_executor=ConfigurationDemoExecutor(delay_seconds=delay),
        task_store=InMemoryTaskStore(),
    )

    api = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()
    uvicorn.run(api, host=HOST, port=PORT)


if __name__ == "__main__":
    app()
