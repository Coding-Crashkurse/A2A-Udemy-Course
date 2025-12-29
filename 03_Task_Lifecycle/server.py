import uuid

import typer
import uvicorn

from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
    TransportProtocol,
)

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

app = typer.Typer(add_completion=False)


class TaskLifecycleExecutor(AgentExecutor):
    def __init__(self, terminal_state: TaskState) -> None:
        self.terminal_state = terminal_state

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        if self.terminal_state == TaskState.completed:
            text = f"Completed Task: Echo: {user_text}"
        elif self.terminal_state == TaskState.rejected:
            text = f"Rejected Task: Validation failed (demo). Input was: {user_text}"
        else:
            text = f"Failed Task: Unexpected error (demo). Input was: {user_text}"

        agent_msg = Message(
            role=Role.agent,
            message_id=str(uuid.uuid4()),
            context_id=context.context_id,
            task_id=context.task_id,
            parts=[Part(root=TextPart(text=text))],
        )

        artifacts = []
        if self.terminal_state == TaskState.completed:
            artifacts = [
                {
                    "artifact_id": "fake-pdf",
                    "name": "fake.pdf",
                    "description": "Fake PDF artifact (placeholder).",
                    "parts": [Part(root=TextPart(text="PDF placeholder content (not a real PDF)."))],
                    "metadata": {"media_type": "application/pdf"},
                }
            ]

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=self.terminal_state, message=agent_msg),
            history=[context.message, agent_msg],
            artifacts=artifacts,
            metadata={"section": "03_Tasks", "terminal_state": self.terminal_state.value},
        )

        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


@app.callback(invoke_without_command=True)
def main(
    completed: bool = typer.Option(False),
    rejected: bool = typer.Option(False),
    failed: bool = typer.Option(False),
) -> None:
    terminal_state = TaskState.failed if failed else TaskState.rejected if rejected else TaskState.completed

    agent_card = AgentCard(
        name="03_Tasks - Fixed Lifecycle Demo Agent (REST)",
        description="REST-only demo: always returns a Task in a fixed terminal state.",
        version="0.3.0-demo",
        url=BASE_URL,
        preferred_transport=TransportProtocol.http_json,
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )

    handler = DefaultRequestHandler(
        agent_executor=TaskLifecycleExecutor(terminal_state=terminal_state),
        task_store=InMemoryTaskStore(),
    )

    api = A2ARESTFastAPIApplication(agent_card=agent_card, http_handler=handler).build()
    uvicorn.run(api, host=HOST, port=PORT)


if __name__ == "__main__":
    app()
