import asyncio
from collections import Counter

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import ListTasksRequest, TaskState

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
            response = await client.list_tasks(ListTasksRequest())
            print(f"total tasks: {response.total_size}")

            by_state = Counter(TaskState.Name(t.status.state) for t in response.tasks)
            for state, count in sorted(by_state.items()):
                print(f"  {state}: {count}")

            failed = await client.list_tasks(
                ListTasksRequest(status=TaskState.TASK_STATE_FAILED)
            )
            print(f"\nfiltered status=FAILED -> {len(failed.tasks)} task(s):")
            for t in failed.tasks:
                print(f"  - {t.id}")
        finally:
            await client.close()


if __name__ == "__main__":
    asyncio.run(main())
