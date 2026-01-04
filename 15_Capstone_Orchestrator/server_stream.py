from __future__ import annotations

import asyncio
import logging
from typing import cast

import uvicorn
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_openai import ChatOpenAI

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Message,
    Part,
    TextPart,
    TransportProtocol,
)
from a2a.utils import new_agent_text_message, new_task

load_dotenv()  # reads OPENAI_API_KEY from .env

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("FootballStreamingAgent")

BASE_URL = "http://localhost:8002"

MODEL = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=650,
    timeout=30,
)


class FootballStreamingExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        agent = create_agent(
            model=MODEL,
            tools=[],
            system_prompt=(
                "Du bist ein Fußball-Experte (Association Football/Soccer).\n"
                "Du darfst NUR über Fußball reden.\n"
                "Wenn die Frage nicht primär Fußball ist, lehne kurz ab und bitte um eine Fußball-Frage.\n"
                "Antworte auf Deutsch, präzise und hilfreich."
            ),
        )

        result = await agent.ainvoke({"messages": [HumanMessage(content=user_text)]})
        answer = cast(str, result["messages"][-1].content)

        task = new_task(cast(Message, context.message))  # immer neuer Task (Happy Path)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # Optionaler "working"-Ping
        await updater.start_work(
            new_agent_text_message(
                "Ich schaue mir das kurz an …",
                context_id=task.context_id,
                task_id=task.id,
            )
        )

        # Stream per Artifact-Chunks (append)
        artifact_id = "football-answer"
        chunk_size = 220
        chunks = [answer[i : i + chunk_size] for i in range(0, len(answer), chunk_size)]

        for idx, chunk in enumerate(chunks):
            last = idx == (len(chunks) - 1)
            await updater.add_artifact(
                parts=[Part(root=TextPart(text=chunk))],
                artifact_id=artifact_id,
                name="answer.txt",
                metadata={"mediaType": "text/plain"},
                append=True if idx > 0 else None,
                last_chunk=True if last else None,
            )
            await asyncio.sleep(0.05)

        # Finaler Task-Status (completed) mit Message
        await updater.complete(
            new_agent_text_message(
                answer,
                context_id=task.context_id,
                task_id=task.id,
            )
        )

        log.info("completed task_id=%s", task.id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


agent_card = AgentCard(
    name="Football Streaming Agent (REST + LLM)",
    description="Darf ausschließlich über Fußball sprechen. Liefert optional Artefakt-Chunks (Streaming).",
    url=BASE_URL,
    version="0.1.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="sports.football.chat",
            name="Fußball Q&A (Streaming)",
            description="Antwortet nur zu Fußball-Themen (Soccer).",
            tags=["football", "soccer", "sports", "streaming"],
            examples=[
                "Wer sind die Favoriten in der Bundesliga?",
                "Erklär mir Abseits kurz und sauber.",
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=FootballStreamingExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=agent_card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
