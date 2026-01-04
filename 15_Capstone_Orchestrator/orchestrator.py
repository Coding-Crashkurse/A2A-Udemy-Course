import json
import logging
from typing import Literal

import httpx
import uvicorn
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from a2a.client import ClientConfig, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client_factory import ClientFactory
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2ARESTFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, TransportProtocol
from a2a.utils import get_message_text, new_agent_text_message, new_task

load_dotenv()

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
    temperature=0.0,
    max_tokens=650,
    timeout=30,
)


class RouteDecision(BaseModel):
    target: Literal["football", "general"] = Field(
        description="Pick 'football' only if the user message is primarily about soccer/football, otherwise 'general'."
    )
    query: str = Field(description="Short explicit query to send to the chosen agent.")
    reason: str = Field(description="Short internal reason for debugging.")


class FinalAnswer(BaseModel):
    answer: str = Field(
        description=(
            "Final user-facing answer in English. Must explicitly mention which agent was consulted. "
            "Must be based only on the remote agent answer."
        )
    )


class OrchestratorExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        timeout = httpx.Timeout(60.0, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as http:
            football_card = await A2ACardResolver(http, FOOTBALL_AGENT_URL).get_agent_card()
            general_card = await A2ACardResolver(http, GENERAL_AGENT_URL).get_agent_card()

            football_card_json = json.dumps(
                football_card.model_dump(exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )
            general_card_json = json.dumps(
                general_card.model_dump(exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )

            football_client = ClientFactory(
                ClientConfig(
                    httpx_client=http,
                    supported_transports=[TransportProtocol.http_json],
                    streaming=True,   # football can stream
                    polling=False,
                )
            ).create(football_card)

            general_client = ClientFactory(
                ClientConfig(
                    httpx_client=http,
                    supported_transports=[TransportProtocol.http_json],
                    streaming=False,
                    polling=False,
                )
            ).create(general_card)

            try:
                router = create_agent(
                    model=ROUTER_MODEL,
                    tools=[],
                    response_format=RouteDecision,
                    system_prompt=(
                        "You are an orchestrator.\n"
                        "CRITICAL RULES:\n"
                        "1) You must NOT answer the user's question yourself.\n"
                        "2) You must ONLY return a routing decision in the required schema.\n"
                        "3) You must select exactly ONE remote agent and produce a short query.\n\n"
                        "Routing rules:\n"
                        "- target='football' only if the question is primarily about soccer.\n"
                        "- otherwise target='general'.\n\n"
                        "FOOTBALL_AGENT_CARD_JSON:\n"
                        f"{football_card_json}\n\n"
                        "GENERAL_AGENT_CARD_JSON:\n"
                        f"{general_card_json}\n"
                    ),
                )

                user_text = context.get_user_input()
                router_result = await router.ainvoke({"messages": [HumanMessage(content=user_text)]})
                decision: RouteDecision = router_result["structured_response"]

                used_card = football_card if decision.target == "football" else general_card
                used_client = football_client if decision.target == "football" else general_client

                outbound = create_text_message_object(content=decision.query)

                events = used_client.send_message(outbound)
                remote_task, _ = await anext(events)
                async for remote_task, _ in events:
                    pass

                remote_text = get_message_text(remote_task.status.message)

                finalizer = create_agent(
                    model=FINALIZER_MODEL,
                    tools=[],
                    response_format=FinalAnswer,
                    system_prompt=(
                        "You are the final formatting step of an orchestrator.\n"
                        "CRITICAL RULES:\n"
                        "1) Do NOT answer from your own knowledge.\n"
                        "2) Use ONLY the provided REMOTE_AGENT_ANSWER.\n"
                        "3) The output MUST clearly state which agent was consulted.\n\n"
                        "Required format:\n"
                        "Start with: I consulted agent \"<NAME>\" (<URL>) and received the following information:\n"
                        "Then include the remote agent answer.\n"
                        "Do not add any new facts.\n"
                    ),
                )

                finalizer_input = (
                    f'AGENT_USED_NAME: "{used_card.name}"\n'
                    f"AGENT_USED_URL: {used_card.url}\n\n"
                    "REMOTE_AGENT_ANSWER:\n"
                    f"{remote_text}\n"
                )

                finalizer_result = await finalizer.ainvoke(
                    {"messages": [HumanMessage(content=finalizer_input)]}
                )
                final: FinalAnswer = finalizer_result["structured_response"]

                task = new_task(context.message)
                await event_queue.enqueue_event(task)

                updater = TaskUpdater(event_queue, task.id, task.context_id)
                await updater.complete(
                    new_agent_text_message(
                        final.answer,
                        context_id=task.context_id,
                        task_id=task.id,
                    )
                )

                log.info(
                    "completed task_id=%s routed_to=%s agent=%s reason=%s",
                    task.id,
                    decision.target,
                    used_card.name,
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
        "Orchestrator agent: never answers questions directly. "
        "It delegates to sub-agents and explicitly states which agent provided the information."
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
            name="Route + Delegate (No Direct Answers)",
            description="Selects exactly one sub-agent, delegates, and returns the result with explicit agent attribution.",
            tags=["orchestrator", "routing", "delegation", "a2a"],
            examples=[
                "Explain the offside rule briefly.",
                "Explain JSON-RPC briefly.",
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
