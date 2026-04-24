import logging

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface

logger = logging.getLogger(__name__)


class EchoExecutor(AgentExecutor):
    """Minimal echo executor reused by all transport demos."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input()
        response = new_text_message(
            text=f"Echo: {user_text}",
            context_id=context.context_id,
            task_id=context.task_id,
        )
        await event_queue.enqueue_event(response)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.warning(
            "Cancel called for task_id=%s, no cancellation logic implemented",
            context.task_id,
        )


def build_agent_card(
    *interfaces: AgentInterface,
) -> AgentCard:
    """Create a compact AgentCard with one or more transport interfaces."""
    return AgentCard(
        name="Echo Agent",
        description="A simple echo service used in transport examples.",
        version="0.2.0",
        supported_interfaces=list(interfaces),
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )


def create_request_handler(
    agent_card: AgentCard,
    executor: AgentExecutor | None = None,
) -> DefaultRequestHandler:
    """Instantiate the default handler with an in-memory task store."""
    return DefaultRequestHandler(
        agent_executor=executor or EchoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
