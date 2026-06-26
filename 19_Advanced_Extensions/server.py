import logging
from pathlib import Path
from typing import cast
from uuid import UUID

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ValidationError

from a2a.helpers import new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    InvalidParamsError,
    Message,
)
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("ChatContextExtensionDemo")

BASE_URL = "http://localhost:8001"

CHAT_EXTENSION_URI = "https://example.com/extensions/chat-context/v1"


class ChatContext(BaseModel):
    """Mandatory chat-context payload carried in message.metadata[CHAT_EXTENSION_URI]."""

    chat_id: UUID


def _require_chat_context(ctx: RequestContext) -> ChatContext:
    msg = cast(Message, ctx.message)
    metadata = MessageToDict(msg.metadata) if msg.metadata else {}

    payload = metadata.get(CHAT_EXTENSION_URI)
    if payload is None:
        raise InvalidParamsError(
            message=f"Missing required extension metadata '{CHAT_EXTENSION_URI}'"
        )

    try:
        return ChatContext.model_validate(payload)
    except ValidationError as exc:
        raise InvalidParamsError(message=f"Invalid chat-context: {exc}") from exc


class ChatContextExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        chat = _require_chat_context(context)

        user_text = context.get_user_input()

        task = new_task_from_user_message(cast(Message, context.message))
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        reply = f"[chat={chat.chat_id}] echo: {user_text}"
        await updater.complete(
            new_text_message(text=reply, context_id=task.context_id, task_id=task.id)
        )

        log.info("completed task_id=%s chat_id=%s", task.id, chat.chat_id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


agent_card = AgentCard(
    name="Chat-Context Extension Demo Agent (REST)",
    description="Echo agent that requires a validated chat-context (chat_id, user_id) in message metadata.",
    version="0.1.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=BASE_URL,
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(
        streaming=False,
        push_notifications=False,
        extensions=[
            {
                "uri": CHAT_EXTENSION_URI,
                "description": "Client must send chat context in message.metadata[URI]; validated server-side via Pydantic.",
                "required": True,
                "params": {"payloadSchema": ChatContext.model_json_schema()},
            }
        ],
    ),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="demo.chat.context",
            name="Chat Context via Extension",
            description="Requires chat_id in metadata; echoes the message back.",
            tags=["demo", "extension", "chat-context"],
            examples=[
                '{"metadata": {"https://example.com/extensions/chat-context/v1": {"chat_id": "c-123"}}}',
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=ChatContextExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=agent_card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
