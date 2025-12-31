import asyncio
import uuid

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TaskState,
    TextPart,
)
from a2a.utils import get_artifact_text, get_message_text

BASE_URL = "http://localhost:8001"


def print_update(task: Task, update) -> None:
    line = f"state={task.status.state.value}"

    if isinstance(update, TaskStatusUpdateEvent) and update.status.message:
        line += f" text={get_message_text(update.status.message)}"

    if isinstance(update, TaskArtifactUpdateEvent):
        line += f" artifact={update.artifact.name} artifactText={get_artifact_text(update.artifact)}"

    print(line)


async def send_streaming_turn(client, msg: Message) -> Task:
    """
    Sendet einen Streaming-Turn und gibt den letzten Task-Snapshot zurück.
    """
    last_task: Task | None = None

    async for task, update in client.send_message(msg):
        last_task = task
        if update is not None:
            print_update(task, update)

    if last_task is None:
        raise RuntimeError("No task received from streaming call")

    return last_task


async def main() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
                streaming=True,
                polling=False,
            ),
        )

        try:
            # --------------------
            # TURN 1: Start
            # --------------------
            start_msg = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                parts=[Part(root=TextPart(text="Start Multi-Turn"))],
            )

            print("\n--- TURN 1 (stream) ---\n")
            task1 = await send_streaming_turn(client, start_msg)

            print(
                f"\nTurn1 done: taskId={task1.id} contextId={task1.context_id} state={task1.status.state.value}\n"
            )

            if task1.status.state != TaskState.input_required:
                raise RuntimeError(f"Expected input_required, got {task1.status.state}")

            # --------------------
            # TURN 2: Antwort (same task_id)
            # --------------------
            answer_text = "Markus"
            followup_msg = Message(
                role=Role.user,
                message_id=str(uuid.uuid4()),
                task_id=task1.id,
                context_id=task1.context_id,
                parts=[Part(root=TextPart(text=answer_text))],
            )

            print("\n--- TURN 2 (stream, same task_id) ---\n")
            task2 = await send_streaming_turn(client, followup_msg)

            print(
                f"\nTurn2 done: taskId={task2.id} contextId={task2.context_id} state={task2.status.state.value}\n"
            )

            if task2.status.state != TaskState.completed:
                raise RuntimeError(f"Expected completed, got {task2.status.state}")

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
