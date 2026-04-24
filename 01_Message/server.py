import logging
import uvicorn
from fastapi import FastAPI
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.helpers import new_text_message
from a2a.types import AgentCard, AgentCapabilities, AgentInterface

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("EchoAgent")


RPC_URL = "/"


class EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info(">>> [1] EXECUTE START: Received new request")

        user_text = context.get_user_input()
        logger.info(f">>> [2] INPUT PARSED: User said '{user_text}'")
        logger.info(
            f">>> [2a] IDs: TaskID={context.task_id}, ContextID={context.context_id}"
        )

        response_text = f"Echo: {user_text}"

        response_message = new_text_message(
            text=response_text,
            context_id=context.context_id,
            task_id=context.task_id,
        )

        logger.info(f">>> [3] RESPONSE CREATED: '{response_text}'")

        await event_queue.enqueue_event(response_message)
        logger.info(">>> [4] EVENT ENQUEUED: Message sent to queue")
        logger.info(">>> [5] EXECUTE END: Handler finished")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.warning(">>> CANCEL REQUESTED (Not implemented for this demo)")


minimal_card = AgentCard(
    name="Minimal Echo Agent",
    description="A simple echo service",
    version="0.1.0",
    supported_interfaces=[
        AgentInterface(
            url="http://localhost:8000/",
            protocol_binding="JSONRPC",
        ),
    ],
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[],
)

task_store = InMemoryTaskStore()
executor = EchoExecutor()

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
    agent_card=minimal_card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=minimal_card):
    app.router.routes.append(route)
for route in create_jsonrpc_routes(request_handler=request_handler, rpc_url=RPC_URL):
    app.router.routes.append(route)

if __name__ == "__main__":
    logger.info("--- Starting A2A Server on Port 8000 ---")
    uvicorn.run(app, host="0.0.0.0", port=8000)
