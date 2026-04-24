import logging
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from a2a.helpers import new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

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
                "You are an expert for association football (soccer).\n"
                "You must ONLY talk about soccer.\n"
                "If the user's question is not primarily about soccer, refuse briefly and ask for a soccer question.\n"
                "Answer in English, precise and helpful."
            ),
        )

        result = await agent.ainvoke({"messages": [HumanMessage(content=user_text)]})
        answer = result["messages"][-1].content

        task = new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.complete(
            new_text_message(
                text=answer,
                context_id=task.context_id,
                task_id=task.id,
            )
        )

        log.info("completed task_id=%s", task.id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


agent_card = AgentCard(
    name="Football Streaming Agent (REST + LLM)",
    description="Soccer-only agent. Advertises streaming=true in AgentCard.",
    version="0.1.0-demo",
    supported_interfaces=[
        AgentInterface(
            url=BASE_URL,
            protocol_binding=TransportProtocol.HTTP_JSON,
        ),
    ],
    capabilities=AgentCapabilities(streaming=True, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="sports.football.chat",
            name="Soccer Q&A (Streaming)",
            description="Answers only soccer-related questions.",
            tags=["football", "soccer", "sports", "streaming"],
            examples=[
                "Explain the offside rule briefly.",
                "How does the Champions League format work?",
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=FootballStreamingExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=agent_card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=agent_card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8002)
