import asyncio
import logging

import typer
import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_text_message
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
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils import TransportProtocol

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

        cfg = context.configuration
        if cfg is None:
            return_immediately = False
            history_length = None
        else:
            return_immediately = (
                bool(cfg.return_immediately)
                if cfg.return_immediately is not None
                else False
            )
            history_length = cfg.history_length
        if history_length is not None and history_length < 0:
            raise InvalidParamsError(message="historyLength must be >= 0")
        
        user_text = context.get_user_input()

        log.info(
            "task_id=%s context_id=%s return_immediately=%s history_length=%r",
            context.task_id,
            context.context_id,
            return_immediately,
            history_length,
        )

        started_msg = new_text_message(
            text="Working...",
            context_id=context.context_id,
            task_id=context.task_id,
        )

        initial_task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING, message=started_msg),
            history=[context.message],
            artifacts=[],
            metadata={
                "section": "04_Configuration",
                "return_immediately": "true" if return_immediately else "false",
            },
        )
        await event_queue.enqueue_event(initial_task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)

        steps = 5
        for i in range(1, steps + 1):
            await asyncio.sleep(self.delay_seconds / steps)
            await updater.update_status(
                TaskState.TASK_STATE_WORKING,
                message=updater.new_agent_message([Part(text=f"step {i}/{steps}")]),
            )

        await updater.add_artifact(
            [Part(text=f"Echo: {user_text}")],
            name="result.txt",
        )
        await updater.complete(
            updater.new_agent_message([Part(text=f"Done. Echo: {user_text}")])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


@app.callback(invoke_without_command=True)
def main(
    delay: float = typer.Option(2.5, help="Simulated work duration (seconds)"),
) -> None:
    card = AgentCard(
        name="04_Configuration Demo Agent (REST)",
        description="Shows return_immediately + historyLength.",
        version="0.4.0-demo",
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
        agent_executor=ConfigurationDemoExecutor(delay_seconds=delay),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    api = FastAPI()
    for route in create_agent_card_routes(agent_card=card):
        api.router.routes.append(route)
    for route in create_rest_routes(request_handler=handler):
        api.router.routes.append(route)

    uvicorn.run(api, host=HOST, port=PORT)


if __name__ == "__main__":
    app()
