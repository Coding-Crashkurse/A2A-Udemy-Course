import asyncio
import time
import uuid

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    MessageSendConfiguration,
    Part,
    Role,
    Task,
    TaskQueryParams,
    TaskState,
    TextPart,
)
from a2a.utils import get_message_text

BASE_URL = "http://localhost:8001"


def fmt_task_line(t: Task) -> str:
    state = t.status.state.value if t.status and t.status.state else "<?>"
    msg = get_message_text(t.status.message) if t.status and t.status.message else ""
    return f"taskId={t.id} contextId={t.context_id} state={state} statusText={msg!r}"


async def create_task_fire_and_forget(client, *, context_id: str, text: str) -> Task:
    msg = Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        context_id=context_id,
        parts=[Part(root=TextPart(text=text))],
    )
    it = client.send_message(msg, configuration=MessageSendConfiguration(blocking=False))
    task, _update = await anext(it)
    await it.aclose()
    return task


async def cancel_task_rest(http: httpx.AsyncClient, task_id: str) -> tuple[int, str]:
    r = await http.post(f"{BASE_URL}/v1/tasks/{task_id}:cancel", json={})
    return r.status_code, r.text


async def wait_for_state(
    client,
    task_id: str,
    target: TaskState,
    *,
    timeout_s: float = 60.0,
    poll_s: float = 1.0,
) -> Task:
    t0 = time.perf_counter()
    last: Task | None = None
    while True:
        last = await client.get_task(TaskQueryParams(id=task_id))
        state = last.status.state
        text = get_message_text(last.status.message) if last.status.message else ""
        elapsed = time.perf_counter() - t0
        print(f"poll t={elapsed:5.1f}s state={state.value} text={text!r}")
        if state == target:
            return last
        if elapsed > timeout_s:
            raise RuntimeError(f"Timeout waiting for {target.value}, last={state.value}")
        await asyncio.sleep(poll_s)


def explain_cancel(status_code: int) -> str:
    if status_code == 200:
        return "OK (cancellation accepted)"
    if status_code == 409:
        return "NOT CANCELABLE (expected for terminal states like canceled/completed)"
    return "UNEXPECTED"


async def main() -> None:
    context_id = str(uuid.uuid4())
    print(f"contextId (shared) = {context_id}")

    async with httpx.AsyncClient(timeout=None) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
                streaming=False,
                polling=False,
            ),
        )

        try:
            # -------------------------
            # Demo A: cancel mid-flight
            # -------------------------
            print("\n=== DEMO A: cancel mid-flight ===")
            t1 = await create_task_fire_and_forget(client, context_id=context_id, text="Job A (cancel me)")
            print("created:", fmt_task_line(t1))

            await asyncio.sleep(2.0)
            cur = await client.get_task(TaskQueryParams(id=t1.id))
            print("current:", fmt_task_line(cur))

            print("\nwaiting 5s then cancel...")
            await asyncio.sleep(5.0)

            code, body = await cancel_task_rest(http, t1.id)
            print(f"cancel #1: http={code} ({explain_cancel(code)}) body={body[:200]}")

            print("\nwait until state=canceled ...")
            canceled_task = await wait_for_state(client, t1.id, TaskState.canceled, timeout_s=20.0)
            print("final:", fmt_task_line(canceled_task))

            # Spec-konform: Cancel auf bereits canceled -> 409 TaskNotCancelableError
            print("\nCancel again (idempotent by effect; expect 409)...")
            code2, body2 = await cancel_task_rest(http, t1.id)
            print(f"cancel #2: http={code2} ({explain_cancel(code2)}) body={body2[:200]}")

            again = await client.get_task(TaskQueryParams(id=t1.id))
            print("after cancel #2:", fmt_task_line(again))

            # -----------------------------------------
            # Demo B: cancel after completion -> 409
            # -----------------------------------------
            print("\n=== DEMO B: cancel after completion (expect 409) ===")
            t2 = await create_task_fire_and_forget(client, context_id=context_id, text="Job B (complete me)")
            print("created:", fmt_task_line(t2))

            print("\nwaiting until completed (~30s)...")
            done = await wait_for_state(client, t2.id, TaskState.completed, timeout_s=80.0)
            print("completed:", fmt_task_line(done))

            print("\nTry cancel on completed task (expect 409)...")
            code3, body3 = await cancel_task_rest(http, t2.id)
            print(f"cancel completed: http={code3} ({explain_cancel(code3)}) body={body3[:400]}")

        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
