import typer
import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Artifact,
    Part,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils import TransportProtocol

HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

app = typer.Typer(add_completion=False)


class TaskLifecycleExecutor(AgentExecutor):
    def __init__(self, terminal_state: int) -> None:
        self.terminal_state = terminal_state

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        if self.terminal_state == TaskState.TASK_STATE_COMPLETED:
            text = f"Completed Task: Echo: {user_text}"
        elif self.terminal_state == TaskState.TASK_STATE_REJECTED:
            text = f"Rejected Task: Validation failed (demo). Input was: {user_text}"
        else:
            text = f"Failed Task: Unexpected error (demo). Input was: {user_text}"

        agent_msg = new_text_message(
            text=text,
            context_id=context.context_id,
            task_id=context.task_id,
        )

        artifacts: list[Artifact] = []
        if self.terminal_state == TaskState.TASK_STATE_COMPLETED:
            artifacts = [
                Artifact(
                    artifact_id="fake-pdf",
                    name="fake.pdf",
                    description="Fake PDF artifact (placeholder).",
                    parts=[
                        Part(text="PDF placeholder content (not a real PDF).")
                    ],
                    metadata={"media_type": "application/pdf"},
                )
            ]

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=self.terminal_state, message=agent_msg),
            history=[context.message, agent_msg],
            artifacts=artifacts,
            metadata={
                "section": "03_Tasks",
                "terminal_state": TaskState.Name(self.terminal_state),
            },
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
    terminal_state = (
        TaskState.TASK_STATE_FAILED
        if failed
        else TaskState.TASK_STATE_REJECTED
        if rejected
        else TaskState.TASK_STATE_COMPLETED
    )

    agent_card = AgentCard(
        name="03_Tasks - Fixed Lifecycle Demo Agent (REST)",
        description="REST-only demo: always returns a Task in a fixed terminal state.",
        version="0.3.0-demo",
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
        agent_executor=TaskLifecycleExecutor(terminal_state=terminal_state),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    api = FastAPI()
    for route in create_agent_card_routes(agent_card=agent_card):
        api.router.routes.append(route)
    for route in create_rest_routes(request_handler=handler):
        api.router.routes.append(route)

    uvicorn.run(api, host=HOST, port=PORT)


if __name__ == "__main__":
    app()
