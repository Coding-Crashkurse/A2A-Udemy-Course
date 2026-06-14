import logging
from pathlib import Path
from typing import cast

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

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
    Message,
)
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("LangExtensionLLMDemo")

BASE_URL = "http://localhost:8001"

LANG_EXTENSION_URI = "https://example.com/extensions/language/v1"
SUPPORTED_LANGUAGES = ["de", "en", "es"]
DEFAULT_LANGUAGE = "en"

MODEL = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=400,
    timeout=30,
)


def _lang_from_message(ctx: RequestContext) -> str:
    msg = cast(Message, ctx.message)
    metadata = MessageToDict(msg.metadata) if msg.metadata else {}
    lang = metadata[LANG_EXTENSION_URI]["language"]
    lang = str(lang).strip().lower()
    return lang.split("-", 1)[0]


class LlmExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        lang = _lang_from_message(context)

        agent = create_agent(
            model=MODEL,
            tools=[],
            system_prompt=f"Talk with the user in the following language: {lang}",
        )

        user_text = context.get_user_input()
        result = await agent.ainvoke({"messages": [HumanMessage(content=user_text)]})
        text = result["messages"][-1].content

        task = new_task_from_user_message(cast(Message, context.message))
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.complete(
            new_text_message(text=text, context_id=task.context_id, task_id=task.id)
        )

        log.info("completed task_id=%s lang=%s", task.id, lang)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


agent_card = AgentCard(
    name="Language Extension Demo Agent (REST + LLM)",
    description="LLM-backed demo: language chosen via extension metadata; system prompt is set per request.",
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
                "uri": LANG_EXTENSION_URI,
                "description": "Client selects language via message.metadata[URI].language",
                "required": False,
                "params": {
                    "supportedLanguages": SUPPORTED_LANGUAGES,
                    "defaultLanguage": DEFAULT_LANGUAGE,
                    "payloadSchema": {"language": "en|de|es"},
                },
            }
        ],
    ),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="demo.language.llm",
            name="Language via Extension (LLM)",
            description="Uses LLM; system prompt enforces language from extension metadata.",
            tags=["demo", "extension", "language", "llm"],
            examples=[
                '{"metadata": {"https://example.com/extensions/language/v1": {"language": "de"}}}',
                '{"metadata": {"https://example.com/extensions/language/v1": {"language": "es"}}}',
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=LlmExecutor(),
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
