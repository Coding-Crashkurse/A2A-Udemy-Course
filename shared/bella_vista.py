import asyncio
import logging
import uuid
from typing import Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Artifact,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskState,
    TextPart,
    TransportProtocol,
)

logger = logging.getLogger(__name__)


def _pick_task_state(*names: str):
    """
    TaskState Enum ist je nach Version leicht unterschiedlich benannt
    (z.B. canceled vs cancelled). Wir picken robust.
    """
    for name in names:
        if hasattr(TaskState, name):
            return getattr(TaskState, name)
    # Fallback: lasse Pydantic/Model layer den String validieren
    return names[0]


STATE_SUBMITTED = _pick_task_state("submitted")
STATE_WORKING = _pick_task_state("working")
STATE_COMPLETED = _pick_task_state("completed")
STATE_CANCELLED = _pick_task_state("cancelled", "canceled")
STATE_FAILED = _pick_task_state("failed")


class BellaVistaExecutor(AgentExecutor):
    """
    Task-basierter Executor:
    - Emit StatusUpdate (working)
    - Simuliere Arbeit
    - Emit ArtifactUpdate (Antwort als Text)
    - Emit StatusUpdate (completed, final=True)
    """

    def __init__(self) -> None:
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = (context.get_user_input() or "").strip()
        task_id = context.task_id
        context_id = context.context_id

        logger.info("execute() task_id=%s context_id=%s input=%r", task_id, context_id, user_text)

        # 1) WORKING Status (mit kurzer Status-Message)
        working_msg = Message(
            role=Role.agent,
            message_id=str(uuid.uuid4()),
            context_id=context_id,
            task_id=task_id,
            parts=[Part(root=TextPart(text="Ich prüfe das kurz für Bella Vista …"))],
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=STATE_WORKING, message=working_msg),
                final=False,
            )
        )

        # 2) Simulierte “Long-running” Arbeit (damit Polling Sinn ergibt)
        #    In kleinen Schritten, damit Cancel zeitnah greift.
        for _ in range(6):
            await asyncio.sleep(0.5)
            async with self._lock:
                if task_id in self._cancelled:
                    cancel_msg = Message(
                        role=Role.agent,
                        message_id=str(uuid.uuid4()),
                        context_id=context_id,
                        task_id=task_id,
                        parts=[Part(root=TextPart(text="Alles klar – ich breche den Task ab."))],
                    )
                    await event_queue.enqueue_event(
                        TaskStatusUpdateEvent(
                            task_id=task_id,
                            context_id=context_id,
                            status=TaskStatus(state=STATE_CANCELLED, message=cancel_msg),
                            final=True,
                        )
                    )
                    return

        # 3) Antwort erzeugen und als Artifact rausgeben
        answer = self._answer_bella_vista(user_text)
        artifact = Artifact(
            artifact_id=str(uuid.uuid4()),
            name="Bella Vista Antwort",
            description="Antwort auf die Nutzerfrage zu Bella Vista",
            parts=[Part(root=TextPart(text=answer))],
        )
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                artifact=artifact,
                append=False,
                last_chunk=True,
            )
        )

        # 4) COMPLETED Status (final=True)
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=STATE_COMPLETED),
                final=True,
            )
        )

        # Cleanup Cancel-Flag (falls gesetzt und doch nicht gegriffen)
        async with self._lock:
            self._cancelled.discard(task_id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        context_id = context.context_id

        logger.warning("cancel() requested for task_id=%s", task_id)

        async with self._lock:
            self._cancelled.add(task_id)

        # Wir emitten hier direkt ein Cancel-StatusUpdate,
        # damit der TaskStore sofort den Terminal-State sieht.
        cancel_msg = Message(
            role=Role.agent,
            message_id=str(uuid.uuid4()),
            context_id=context_id,
            task_id=task_id,
            parts=[Part(root=TextPart(text="Cancel wurde angefordert."))],
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task_id,
                context_id=context_id,
                status=TaskStatus(state=STATE_CANCELLED, message=cancel_msg),
                final=True,
            )
        )

    def _answer_bella_vista(self, user_text: str) -> str:
        q = (user_text or "").lower()

        # Mini-FAQ / Knowledge Base (absichtlich statisch für Kurs-Demo)
        opening_hours = (
            "Öffnungszeiten (Bella Vista):\n"
            "- Mo–Do: 11:00–22:00\n"
            "- Fr–Sa: 11:00–23:00\n"
            "- So: 12:00–21:00\n"
            "Hinweis: Küche schließt jeweils 30 Minuten vor Ladenschluss."
        )
        address = (
            "Adresse (Bella Vista):\n"
            "Bella Vista\n"
            "Seestraße 12\n"
            "12345 Musterstadt"
        )
        phone = "Telefon (Bella Vista): +49 30 1234 5678"
        reservations = (
            "Reservierung (Bella Vista):\n"
            "- Telefonisch: +49 30 1234 5678\n"
            "- Oder vor Ort\n"
            "Tipp: Am Wochenende besser vorher reservieren."
        )
        menu = (
            "Speisekarte (Bella Vista):\n"
            "Für die Demo habe ich keine echte Speisekarte hinterlegt.\n"
            "Frag mich gern nach Empfehlungen (z.B. vegetarisch, Pasta, Pizza)."
        )

        if any(k in q for k in ["öffnungszeiten", "geöffnet", "offen", "wann habt", "wann seid", "uhrzeit"]):
            return opening_hours

        if any(k in q for k in ["adresse", "wo seid", "wo ist", "anschrift", "location", "standort"]):
            return address

        if any(k in q for k in ["telefon", "nummer", "anrufen", "ruf", "call"]):
            return phone

        if any(k in q for k in ["reserv", "tisch", "buch", "booking"]):
            return reservations

        if any(k in q for k in ["speisekarte", "menü", "menu", "karte", "essen", "gerichte"]):
            return menu

        # Default / Help
        return (
            "Ich beantworte Fragen zu **Bella Vista**.\n\n"
            "Beispiele:\n"
            "- „Wie sind die Öffnungszeiten vom Bella Vista?“\n"
            "- „Wie lautet die Adresse vom Bella Vista?“\n"
            "- „Kann ich einen Tisch reservieren?“\n"
            "- „Wie ist die Telefonnummer?“"
        )


def build_agent_card(base_url: str) -> AgentCard:
    """
    Compact AgentCard für REST-only.
    """
    return AgentCard(
        name="Bella Vista Info Agent",
        description="Beantwortet Fragen zu Bella Vista (Öffnungszeiten, Adresse, Kontakt, Reservierung).",
        version="0.3.0",
        url=base_url,
        preferred_transport=TransportProtocol.http_json,
        additional_interfaces=[],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
    )


def create_request_handler(executor: Optional[AgentExecutor] = None) -> DefaultRequestHandler:
    return DefaultRequestHandler(
        agent_executor=executor or BellaVistaExecutor(),
        task_store=InMemoryTaskStore(),
    )
