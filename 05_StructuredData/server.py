import logging
import uuid
from typing import Literal, TypedDict, cast

import uvicorn
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from a2a.helpers import new_message
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("05_StructuredData")


TicketStatus = Literal["open", "closed"]
TicketPriority = Literal["low", "medium", "high"]


class Ticket(TypedDict):
    id: str
    title: str
    status: TicketStatus
    priority: TicketPriority


class ListTicketsRequest(TypedDict, total=False):
    action: Literal["list_tickets"]
    status: TicketStatus


class ListTicketsResponse(TypedDict):
    action: Literal["list_tickets_result"]
    status: TicketStatus
    count: int
    tickets: list[Ticket]


FAKE_TICKETS: list[Ticket] = [
    {
        "id": "INC-1001",
        "title": "VPN login fails",
        "status": "open",
        "priority": "high",
    },
    {
        "id": "INC-1002",
        "title": "Laptop battery swelling",
        "status": "open",
        "priority": "medium",
    },
    {
        "id": "INC-1003",
        "title": "Access request: Jira",
        "status": "closed",
        "priority": "low",
    },
]


def _filter_tickets(status: TicketStatus) -> list[Ticket]:
    return [t for t in FAKE_TICKETS if t["status"] == status]


def get_data_parts(parts):
    out = []
    for p in parts:
        if p.HasField("data"):
            out.append(MessageToDict(p.data))
    return out


def _struct_from_dict(d: dict) -> Struct:
    s = Struct()
    s.update(d)
    return s


class StructuredDataExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise InvalidParamsError(message="missing message")

        data_parts = get_data_parts(context.message.parts)
        if not data_parts:
            raise InvalidParamsError(message="expected DataPart in message.parts")

        req = cast(ListTicketsRequest, data_parts[0])
        action = req.get("action", "list_tickets")
        if action != "list_tickets":
            raise InvalidParamsError(message=f"unsupported action: {action}")

        status = cast(TicketStatus, req.get("status", "open"))
        tickets = _filter_tickets(status)

        payload: ListTicketsResponse = {
            "action": "list_tickets_result",
            "status": status,
            "count": len(tickets),
            "tickets": tickets,
        }

        agent_msg = new_message(
            parts=[
                Part(text=f"Found {len(tickets)} tickets (status={status})."),
                Part(data=_struct_from_dict(cast(dict, payload))),
            ],
            context_id=context.context_id,
            task_id=context.task_id,
        )

        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="tickets.json",
            description="Ticket list as JSON (DataPart).",
            parts=[Part(data=_struct_from_dict(cast(dict, payload)))],
            metadata={"media_type": "application/json"},
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED, message=agent_msg),
            history=[context.message, agent_msg],
            artifacts=[artifact],
            metadata={"section": "05_StructuredData"},
        )

        log.info(
            "completed task_id=%s context_id=%s count=%s",
            task.id,
            task.context_id,
            payload["count"],
        )
        await event_queue.enqueue_event(task)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="05 Structured Data Demo Agent (REST)",
    description="Demonstrates DataPart request/response (structured JSON) + optional DataPart artifact.",
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
