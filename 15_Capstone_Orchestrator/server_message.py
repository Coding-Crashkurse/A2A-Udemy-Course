import logging

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
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, TransportProtocol
from a2a.utils import new_agent_text_message, new_task

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("GeneralMessageAgent")

BASE_URL = "http://localhost:8003"

MODEL = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    max_tokens=650,
    timeout=30,
)


class GeneralMessageExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()

        agent = create_agent(
            model=MODEL,
            tools=[],
            system_prompt=(
                "You are a general assistant.\n"
                "Answer in English.\n"
                "Be concise and practical."
            ),
        )

        result = await agent.ainvoke({"messages": [HumanMessage(content=user_text)]})
        answer = result["messages"][-1].content

        task = new_task(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
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
    name="General Message Agent (REST + LLM)",
    description="General-purpose agent. Advertises streaming=false in AgentCard.",
    url=BASE_URL,
    version="0.1.0-demo",
    protocol_version="0.3.0",
    preferred_transport=TransportProtocol.http_json,
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="general.chat",
            name="General Q&A",
            description="Answers general questions.",
            tags=["general", "chat", "llm"],
            examples=[
                "Explain JSON-RPC briefly.",
                "Give me 5 dinner ideas.",
            ],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ],
)

handler = DefaultRequestHandler(
    agent_executor=GeneralMessageExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2ARESTFastAPIApplication(agent_card=agent_card, http_handler=handler).build()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8003)
