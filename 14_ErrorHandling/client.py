"""A2A error-handling demo client.

The pattern: call a high-level client method, catch the typed `A2AError`.
Every protocol error in the A2A catalog is an `A2AError` subclass, so you can
catch a specific one (TaskNotFoundError) or the base class as a catch-all.
"""

import asyncio

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import new_text_message
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    Role,
    SendMessageRequest,
    TaskPushNotificationConfig,
)
from a2a.utils.errors import (
    A2AError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
)

BASE_URL = "http://localhost:8014"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
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
            # 1) Look up a task that doesn't exist -> TaskNotFoundError (404).
            try:
                await client.get_task(GetTaskRequest(id="does-not-exist"))
            except TaskNotFoundError as e:
                print(f"TaskNotFoundError: {e.message!r}")

            # 2) Cancel a task that already finished -> TaskNotCancelableError (409).
            #    QuickExecutor completes the task before send_message returns.
            done = None
            request = SendMessageRequest(
                message=new_text_message(text="quick job", role=Role.ROLE_USER)
            )
            async for reply in client.send_message(request):
                if reply.HasField("task"):
                    done = reply.task

            try:
                await client.cancel_task(CancelTaskRequest(id=done.id))
            except TaskNotCancelableError as e:
                print(f"TaskNotCancelableError: {e.message!r}")

            # 3) Use a capability the agent doesn't advertise (push_notifications
            #    =False) -> PushNotificationNotSupportedError (400).
            try:
                await client.create_task_push_notification_config(
                    TaskPushNotificationConfig(
                        task_id=done.id, url="http://localhost:9999/hook"
                    )
                )
            except PushNotificationNotSupportedError as e:
                print(f"PushNotificationNotSupportedError: {e.message!r}")

            # 4) Catch-all: any protocol error is an A2AError subclass.
            try:
                await client.get_task(GetTaskRequest(id="another-missing-task"))
            except A2AError as e:
                print(f"caught as base A2AError: {type(e).__name__}")
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
