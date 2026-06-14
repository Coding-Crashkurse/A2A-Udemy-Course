import asyncio

import httpx
import uvicorn
from fastapi import FastAPI

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.context import ServerCallContext
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
    TaskUpdater,
)
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Part,
    TaskState,
)
from a2a.utils import TransportProtocol

HOST = "localhost"
PORT = 8001


class PushOnlyDemoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 1/3...")]),
        )
        await asyncio.sleep(2.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 2/3...")]),
        )
        await asyncio.sleep(2.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 3/3...")]),
        )
        await asyncio.sleep(2.0)

        await updater.add_artifact(
            [Part(text="Demo artifact text ✅")],
            name="result.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(text="Task ist beendet ✅")])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="Push Demo Agent (REST Webhook, no SSE)",
    description="No streaming: sends task updates via push notifications (webhook).",
    version="0.4.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=f"http://{HOST}:{PORT}",
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=False, push_notifications=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

push_config_store = InMemoryPushNotificationConfigStore()
push_http = httpx.AsyncClient(timeout=10.0)
push_sender = BasePushNotificationSender(push_http, push_config_store, ServerCallContext())

handler = DefaultRequestHandler(
    agent_executor=PushOnlyDemoExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
    push_config_store=push_config_store,
    push_sender=push_sender,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await push_http.aclose()


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
