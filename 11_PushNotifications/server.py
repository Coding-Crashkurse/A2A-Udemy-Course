import asyncio

import httpx
import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
    TaskUpdater,
)
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


class PushOnlyDemoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 1/3..."))]),
        )
        await asyncio.sleep(2.0)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 2/3..."))]),
        )
        await asyncio.sleep(2.0)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 3/3..."))]),
        )
        await asyncio.sleep(2.0)

        await updater.add_artifact(
            [Part(root=TextPart(text="Demo artifact text ✅"))],
            name="result.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(root=TextPart(text="Task ist beendet ✅"))])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="Push Demo Agent (REST Webhook, no SSE)",
    description="No streaming: sends task updates via push notifications (webhook).",
    url=f"http://{HOST}:{PORT}",
    version="0.4.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    additional_interfaces=[],
    capabilities=AgentCapabilities(streaming=False, push_notifications=True),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

push_config_store = InMemoryPushNotificationConfigStore()
push_http = httpx.AsyncClient(timeout=10.0)
push_sender = BasePushNotificationSender(push_http, push_config_store)

handler = DefaultRequestHandler(
    agent_executor=PushOnlyDemoExecutor(),
    task_store=InMemoryTaskStore(),
    push_config_store=push_config_store,
    push_sender=push_sender,
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await push_http.aclose()


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
