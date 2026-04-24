import asyncio
import uuid

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text
from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskState,
)

BASE_URL = "http://localhost:8001"


async def send_streaming_turn(client, msg: Message):
    last_state = None
    last_task_id = None
    last_context_id = None

    request = SendMessageRequest(message=msg)
    async for reply in client.send_message(request):
        if reply.HasField("task"):
            t = reply.task
            last_state = t.status.state
            last_task_id = t.id
            last_context_id = t.context_id
            print(f"state={TaskState.Name(t.status.state)} (snapshot)")
        elif reply.HasField("status_update"):
            su = reply.status_update
            last_state = su.status.state
            last_task_id = su.task_id
            last_context_id = su.context_id
            line = f"state={TaskState.Name(su.status.state)}"
            if su.status.HasField("message"):
                line += f" text={get_message_text(su.status.message)}"
            print(line)
        elif reply.HasField("artifact_update"):
            au = reply.artifact_update
            last_task_id = au.task_id
            last_context_id = au.context_id
            print(
                f"artifact={au.artifact.name}"
                f" artifactText={get_artifact_text(au.artifact)}"
            )

    if last_state is None:
        raise RuntimeError("No task received from streaming call")

    return last_state, last_task_id, last_context_id


async def main() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await create_client(
            card,
            client_config=ClientConfig(
                supported_protocol_bindings=[
                    card.supported_interfaces[0].protocol_binding
                ],
                httpx_client=http,
                streaming=True,
                polling=False,
            ),
        )

        try:
            start_msg = Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                parts=[Part(text="Start Multi-Turn")],
            )

            print("\n--- TURN 1 (stream) ---\n")
            state1, task_id, context_id = await send_streaming_turn(client, start_msg)

            print(
                f"\nTurn1 done: taskId={task_id} contextId={context_id} state={TaskState.Name(state1)}\n"
            )

            if state1 != TaskState.TASK_STATE_INPUT_REQUIRED:
                raise RuntimeError(
                    f"Expected input_required, got {TaskState.Name(state1)}"
                )

            answer_text = "Markus"
            followup_msg = Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                task_id=task_id,
                context_id=context_id,
                parts=[Part(text=answer_text)],
            )

            print("\n--- TURN 2 (stream, same task_id) ---\n")
            state2, task_id2, context_id2 = await send_streaming_turn(
                client, followup_msg
            )

            print(
                f"\nTurn2 done: taskId={task_id2} contextId={context_id2} state={TaskState.Name(state2)}\n"
            )

            if state2 != TaskState.TASK_STATE_COMPLETED:
                raise RuntimeError(
                    f"Expected completed, got {TaskState.Name(state2)}"
                )

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
