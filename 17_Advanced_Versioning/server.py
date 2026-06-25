import logging

import uvicorn
from fastapi import FastAPI

from a2a.helpers import get_message_text, new_task_from_user_message
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
)
from a2a.utils import TransportProtocol

HOST: str = "0.0.0.0"
PORT: int = 8001
BASE_URL: str = f"http://localhost:{PORT}"

AGENT_VERSION: str = "1.0.0"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work(updater.new_agent_message([Part(text="Working...")]))
        await updater.add_artifact(
            [Part(text=f"Echo: {get_message_text(context.message)}")], name="echo.txt"
        )
        await updater.complete(updater.new_agent_message([Part(text="Done")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="Versioning Demo (Echo)",
        description="Echo agent for the A2A versioning demo.",
        version=AGENT_VERSION,
        supported_interfaces=[
            AgentInterface(url=BASE_URL, protocol_binding=TransportProtocol.HTTP_JSON),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )


def build_app() -> FastAPI:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=EchoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    app = FastAPI()
    for route in create_agent_card_routes(agent_card=card):
        app.router.routes.append(route)
    for route in create_rest_routes(request_handler=handler):
        app.router.routes.append(route)

    return app


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
