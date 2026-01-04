from __future__ import annotations

import json
import logging
from typing import Literal, cast

import httpx
import uvicorn
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Message, TransportProtocol, Task
from a2a.utils import get_message_text, new_agent_text_message, new_task

load_dotenv()  # reads OPENAI_API_KEY from .env

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("Orchestrator")

BASE_URL = "http://localhost:8001"
FOOTBALL_AGENT_URL = "http://localhost:8002"
GENERAL_AGENT_URL = "http://localhost:8003"

ROUTER_MODEL = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.0,
    max_tokens=250,
    timeout=30,
)

FINALIZER_MODEL = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=650,
    timeout=30,
)


class RouteDecision(BaseModel):
    """Routing decision for which remote agent to call."""

    target: Literal["football", "general"] = Field(
        description="Pick 'football' if the user message is primarily about soccer/football, otherwise 'general'."
    )
    query: str = Field(
        description="The text to send to the chosen agent. Keep it short, explicit, and in the user's language."
    )
    reason: str = Field(description="Short internal reason for debugging.")


class FinalAnswer(BaseModel):
    """Final answer returned by orchestrator."""

    answer: str = Field(description="Final user-facing answer in German.")


class OrchestratorExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        async with httpx.AsyncClient() as http:
            # --- Load AgentCards (known URLs, well-known path) ---
            football_card = await A2ACardResolver(http, FOOTBALL_AGENT_URL).get_agent_card()
            general_card = await A2ACardResolver(http, GENERAL_AGENT_URL).get_agent_card()

            football_card_json = json.dumps(
                football_card.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )
            general_card_json = json.dumps(
                general_card.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )

            # --- Connect clients (orchestrator is a client, too) ---
            football_client = await ClientFactory.connect(
                football_card,
                client_config=ClientConfig(
                    streaming=True,
                    polling=False,
                    supported_transports=[football_card.preferred_transport],
                    httpx_client=http,
                ),
            )
            general_client = await ClientFactory.connect(
                general_card,
                client_config=ClientConfig(
                    streaming=True,
                    polling=False,
                    supported_transports=[general_card.preferred_transport],
                    httpx_client=http,
                ),
            )

            try:
                # --- Step 1: Router (Structured Output) ---
                router_prompt = (
                    "Du bist ein Orchestrator, der genau EINEN Remote-Agenten auswählt.\n"
                    "Du bekommst zwei A2A AgentCards als JSON.\n"
                    "Wähle target='football' nur, wenn die User-Frage primär Fußball (Soccer) ist.\n"
                    "Sonst target='general'.\n"
                    "Erzeuge zusätzlich 'query' (kurz & explizit), die an den gewählten Agenten geschickt wird.\n"
                    "Antworte mit dem strukturierten Schema.\n\n"
                    "FOOTBALL_AGENT_CARD_JSON:\n"
                    f"{football_card_json}\n\n"
                    "GENERAL_AGENT_CARD_JSON:\n"
                    f"{general_card_json}\n"
                )

                router = create_agent(
                    model=ROUTER_MODEL,
                    tools=[],
                    response_format=RouteDecision,
                    system_prompt=router_prompt,
                )

                router_result = await router.ainvoke(
                    {"messages": [HumanMessage(content=user_text)]}
                )
                decision = cast(RouteDecision, router_result["structured_response"])

                target_client = football_client if decision.target == "football" else general_client

                # --- Call chosen agent ---
                outbound = create_text_message_object(content=decision.query)

                last_task: Task | None = None
                last_message_text: str | None = None

                async for ev in target_client.send_message(outbound):
                    if isinstance(ev, tuple):
                        task, _update = ev
                        last_task = task
                    else:
                        # Rare: agent replies with a direct Message (no task)
                        last_message_text = get_message_text(ev)

                agent_answer = (
                    get_message_text(cast(Message, last_task.status.message))
                    if (last_task is not None and last_task.status.message is not None)
                    else cast(str, last_message_text)
                )

                # --- Step 2: Finalizer (Structured Output) ---
                finalizer_prompt = (
                    "Du bist die letzte Schicht des Orchestrators.\n"
                    "Du bekommst: User-Frage, Routing-Entscheidung, Antwort vom Remote-Agent.\n"
                    "Gib dem User eine saubere, direkte Antwort auf Deutsch.\n"
                    "Keine Meta-Erklärungen über Routing, AgentCards oder Orchestrierung.\n"
                    "Wenn die Remote-Antwort schon gut ist, gib sie praktisch 1:1 weiter (leicht polieren ist ok).\n"
                )

                finalizer = create_agent(
                    model=FINALIZER_MODEL,
                    tools=[],
                    response_format=FinalAnswer,
                    system_prompt=finalizer_prompt,
                )

                finalizer_input = (
                    "USER:\n"
                    f"{user_text}\n\n"
                    "ROUTE_DECISION:\n"
                    f"{decision.model_dump_json(ensure_ascii=False)}\n\n"
                    "REMOTE_AGENT_ANSWER:\n"
                    f"{agent_answer}\n"
                )

                finalizer_result = await finalizer.ainvoke(
                    {"messages": [HumanMessage(content=finalizer_input)]}
                )
                final = cast(FinalAnswer, finalizer_result["structured_response"]).answer

                # --- Return as Task (happy path) ---
                task = new_task(cast(Message, context.message))
                await event_queue.enqueue_event(task)

                updater = TaskUpdater(event_queue, task.id, task.context_id)
                await updater.complete(
                    new_agent_text_message(
                        final,
                        context_id=task.context_id,
                        task_id=task.id,
                    )
                )

                log.info(
                    "completed task_id=%s routed_to=%s reason=%s",
                    task.id,
                    decision.target,
                    decision.reason,
                )

            finally:
                await football_client.close()
                await general_client.close()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


agent_card = AgentCard(
    name="Orchestrator Agent (REST) - Routes to 2 sub-agents",
    description=(
        "Orchestriert zwei Remote-Agenten via deren AgentCards. "
        "Routing erfolgt per LLM Structured Output."
    ),
    url=BASE_URL,
    version="0.1.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="orchestrator.route_and_delegate",
            name="Route + Delegate",
            description="Wählt zwischen Football-Agent (streaming) und General-Agent (message) und delegiert.",
            tags=["orchestrator", "routing", "delegation", "a2a"],
            examples=[
                "Wer hat gestern in der Bundesliga gewonnen?",
                "Erklär mir kurz, wie JSON-RPC funktioniert.",
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=OrchestratorExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=agent_card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
