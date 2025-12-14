import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Message,
    Part,
    Role,
    TextPart,
    TransportProtocol,
)

logger = logging.getLogger(__name__)


class EchoExecutor(AgentExecutor):
    """Minimal echo executor reused by all transport demos."""

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        user_text = context.get_user_input()
        response = Message(
            role=Role.agent,
            message_id=str(uuid.uuid4()),
            context_id=context.context_id,
            task_id=context.task_id,
            parts=[Part(root=TextPart(text=f'Echo: {user_text}'))],
        )
        await event_queue.enqueue_event(response)

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        logger.warning(
            'Cancel called for task_id=%s, no cancellation logic implemented',
            context.task_id,
        )


def build_agent_card(
    base_url: str,
    preferred_transport: TransportProtocol | str,
    *,
    additional_interfaces: list[AgentInterface] | None = None,
) -> AgentCard:
    """Create a compact AgentCard tailored to a single transport."""
    return AgentCard(
        name='Echo Agent',
        description='A simple echo service used in transport examples.',
        version='0.2.0',
        url=base_url,
        preferred_transport=preferred_transport,
        additional_interfaces=additional_interfaces or [],
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False
        ),
        default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],
        skills=[],
    )


def create_request_handler(
    executor: AgentExecutor | None = None,
) -> DefaultRequestHandler:
    """Instantiate the default handler with an in-memory task store."""
    return DefaultRequestHandler(
        agent_executor=executor or EchoExecutor(),
        task_store=InMemoryTaskStore(),
    )
