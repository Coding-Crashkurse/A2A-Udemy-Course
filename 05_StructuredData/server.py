import logging
import uuid
from typing import Literal, TypedDict, cast

import uvicorn

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    Artifact,
    DataPart,
    InvalidParamsError,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_agent_parts_message
from a2a.utils.errors import ServerError
from a2a.utils.parts import get_data_parts


HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("05_StructuredData")


# -----------------------------
# Typed Structured Payloads
# -----------------------------
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


class StructuredDataExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message is None:
            raise ServerError(InvalidParamsError(message="missing message"))

        data_parts = get_data_parts(context.message.parts)
        if not data_parts:
            raise ServerError(
                InvalidParamsError(message="expected DataPart in message.parts")
            )

        req = cast(ListTicketsRequest, data_parts[0])
        action = req.get("action", "list_tickets")
        if action != "list_tickets":
            raise ServerError(
                InvalidParamsError(message=f"unsupported action: {action}")
            )

        status = cast(TicketStatus, req.get("status", "open"))
        tickets = _filter_tickets(status)

        payload: ListTicketsResponse = {
            "action": "list_tickets_result",
            "status": status,
            "count": len(tickets),
            "tickets": tickets,
        }

        agent_msg = new_agent_parts_message(
            parts=[
                Part(
                    root=TextPart(
                        text=f"Found {len(tickets)} tickets (status={status})."
                    )
                ),
                Part(root=DataPart(data=cast(dict, payload))),
            ],
            context_id=context.context_id,
            task_id=context.task_id,
        )

        # Optional: zusätzlich als Artifact, damit "structured deliverable" sichtbar wird.
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="tickets.json",
            description="Ticket list as JSON (DataPart).",
            parts=[Part(root=DataPart(data=cast(dict, payload)))],
            metadata={"media_type": "application/json"},
        )

        task = Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.completed, message=agent_msg),
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
    url=BASE_URL,
    version="0.5.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    # nice-to-have: signal that JSON is supported
    default_input_modes=["application/json", "text/plain"],
    default_output_modes=["application/json", "text/plain"],
    skills=[],
)

handler = DefaultRequestHandler(
    agent_executor=StructuredDataExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
