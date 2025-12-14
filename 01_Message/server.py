import uuid
import logging
import uvicorn
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    AgentCard, 
    AgentCapabilities, 
    Message, 
    Role, 
    Part, 
    TextPart
)

# Configure logging to see exactly what happens
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("EchoAgent")

class EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info(">>> [1] EXECUTE START: Received new request")
        
        user_text = context.get_user_input()
        logger.info(f">>> [2] INPUT PARSED: User said '{user_text}'")
        logger.info(f">>> [2a] IDs: TaskID={context.task_id}, ContextID={context.context_id}")

        response_text = f"Echo: {user_text}"
        
        response_message = Message(
            role=Role.agent,
            message_id=str(uuid.uuid4()),
            context_id=context.context_id, 
            task_id=context.task_id,
            parts=[
                Part(root=TextPart(text=response_text))
            ]
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
    url="http://localhost:8000/a2a",
    preferred_transport="JSONRPC",
    capabilities=AgentCapabilities(
        streaming=False, 
        push_notifications=False
    ),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[]
)

task_store = InMemoryTaskStore()
executor = EchoExecutor()

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store
)

app_builder = A2AFastAPIApplication(
    agent_card=minimal_card,
    http_handler=request_handler
)

app = app_builder.build(rpc_url="/")

if __name__ == "__main__":
    logger.info("--- Starting A2A Server on Port 8000 ---")
    uvicorn.run(app, host="0.0.0.0", port=8000)