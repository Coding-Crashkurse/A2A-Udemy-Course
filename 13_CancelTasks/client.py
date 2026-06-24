import asyncio

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import new_text_message
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    TaskNotCancelableError,
    TaskState,
)

BASE_URL = "http://localhost:8001"


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
                streaming=False,
                polling=False,
            ),
        )

        try:
            print("=== cancel mid-flight ===")
            request = SendMessageRequest(
                message=new_text_message(
                    text="long job (cancel me)", role=Role.ROLE_USER
                ),
                configuration=SendMessageConfiguration(return_immediately=True),
            )
            task = None
            async for reply in client.send_message(request):
                if reply.HasField("task"):
                    task = reply.task
                    break
            print(f"created: {task.id} state={TaskState.Name(task.status.state)}")

            await asyncio.sleep(3.0)
            canceled = await client.cancel_task(CancelTaskRequest(id=task.id))
            print(f"after cancel: state={TaskState.Name(canceled.status.state)}")

            await asyncio.sleep(3.0)
            later = await client.get_task(GetTaskRequest(id=task.id))
            print(
                f"3s later: state={TaskState.Name(later.status.state)}"
                " (execute() was stopped)"
            )

            print("\n=== cancel again (terminal -> not cancelable) ===")
            try:
                await client.cancel_task(CancelTaskRequest(id=task.id))
            except TaskNotCancelableError as e:
                print(f"rejected as expected: {type(e).__name__}: {e}")
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
