import uvicorn
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Value

from a2a.helpers import new_artifact, new_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
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

FAKE_TICKETS = [
    {"id": "INC-1001", "title": "VPN login fails", "status": "open", "priority": "high"},
    {"id": "INC-1002", "title": "Laptop battery swelling", "status": "open", "priority": "medium"},
    {"id": "INC-1003", "title": "Access request: Jira", "status": "closed", "priority": "low"},
]


class StructuredDataExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise InvalidParamsError(message="missing message")

        request = next(
            (MessageToDict(p.data) for p in context.message.parts if p.HasField("data")),
            None,
        )
        if request is None:
            raise InvalidParamsError(message="expected DataPart in message.parts")

        status = request.get("status", "open")
        tickets = [t for t in FAKE_TICKETS if t["status"] == status]

        payload = Value()
        payload.struct_value.update(
            {"status": status, "count": len(tickets), "tickets": tickets}
        )

        agent_msg = new_message(
            parts=[
                Part(text=f"Found {len(tickets)} '{status}' tickets. Data is in the DataPart.")
            ],
            context_id=context.context_id,
            task_id=context.task_id,
        )

        artifact = new_artifact(
            parts=[Part(data=payload)],
            name="tickets.json",
            description="Ticket list as structured JSON (DataPart).",
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=agent_msg),
            history=[context.message, agent_msg],
            artifacts=[artifact],
        )
        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="05 Structured Data Demo Agent (REST)",
    description="Demonstrates DataPart request/response (structured JSON) plus a JSON artifact.",
    version="0.5.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=BASE_URL,
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["application/json", "text/plain"],
    default_output_modes=["application/json", "text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=StructuredDataExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
