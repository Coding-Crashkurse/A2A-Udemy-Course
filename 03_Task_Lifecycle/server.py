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
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        # Demo only: we simulate the agent's *internal* outcome from a keyword
        # in the message. In a real agent this decision would come from its own
        # validation logic, an exception, a downstream failure, etc. — never
        # from the raw user text. This is just a convenient way to watch all
        # three terminal states without restarting the server.
        lowered = user_text.lower()
        if "reject" in lowered:
            terminal_state = TaskState.TASK_STATE_REJECTED
        elif "fail" in lowered:
            terminal_state = TaskState.TASK_STATE_FAILED
        else:
            terminal_state = TaskState.TASK_STATE_COMPLETED

        artifacts: list[Artifact] = []
        if terminal_state == TaskState.TASK_STATE_COMPLETED:
            # The deliverable lives in an ARTIFACT. The status message below only
            # talks *about* the outcome — it is not the result itself.
            text = "Task completed. The result is attached as an artifact."
            artifacts = [
                Artifact(
                    artifact_id="result",
                    name="result",
                    description="The task's actual output.",
                    parts=[Part(text=f"Echo: {user_text}")],
                )
            ]
        elif terminal_state == TaskState.TASK_STATE_REJECTED:
            text = f"Rejected Task: Validation failed (demo). Input was: {user_text}"
        else:
            text = f"Failed Task: Unexpected error (demo). Input was: {user_text}"

        agent_msg = new_text_message(
            text=text,
            context_id=context.context_id,
            task_id=context.task_id,
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=terminal_state, message=agent_msg),
            history=[context.message, agent_msg],
            artifacts=artifacts,
            metadata={
                "section": "03_Tasks",
                "terminal_state": TaskState.Name(terminal_state),
            },
        )

        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


@app.callback(invoke_without_command=True)
def main() -> None:
    agent_card = AgentCard(
        name="03_Tasks - Lifecycle Demo Agent (REST)",
        description="REST-only demo: returns a Task whose terminal state depends on the input.",
        version="1.0.x-demo",
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
        agent_executor=TaskLifecycleExecutor(),
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
