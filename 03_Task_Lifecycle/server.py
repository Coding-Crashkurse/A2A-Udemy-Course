import typer
import uvicorn
from fastapi import FastAPI

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

        lowered = user_text.lower()
        if "reject" in lowered:
            terminal_state = TaskState.TASK_STATE_REJECTED
        elif "fail" in lowered:
            terminal_state = TaskState.TASK_STATE_FAILED
        else:
            terminal_state = TaskState.TASK_STATE_COMPLETED

        submitted_task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[context.message],
            metadata={
                "section": "03_Tasks",
                "terminal_state": TaskState.Name(terminal_state),
            },
        )
        await event_queue.enqueue_event(submitted_task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        await updater.start_work(
            updater.new_agent_message([Part(text="Working on your task...")])
        )

        if terminal_state == TaskState.TASK_STATE_COMPLETED:
            await updater.add_artifact(
                [Part(text=f"Echo: {user_text}")],
                name="result",
            )
            await updater.complete(
                updater.new_agent_message(
                    [
                        Part(
                            text="Task completed. The result is attached as an artifact."
                        )
                    ]
                )
            )
        elif terminal_state == TaskState.TASK_STATE_REJECTED:
            await updater.reject(
                updater.new_agent_message(
                    [
                        Part(
                            text=f"Rejected Task: Validation failed (demo). Input was: {user_text}"
                        )
                    ]
                )
            )
        else:
            await updater.failed(
                updater.new_agent_message(
                    [
                        Part(
                            text=f"Failed Task: Unexpected error (demo). Input was: {user_text}"
                        )
                    ]
                )
            )

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
