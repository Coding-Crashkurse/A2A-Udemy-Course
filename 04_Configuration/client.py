import asyncio
import time

import httpx
import typer

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import (
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    Task,
    TaskState,
)

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


def print_task(task: Task) -> None:
    print(f"state={TaskState.Name(task.status.state)}")

    print(f"historyCount={len(task.history)}")
    for i, m in enumerate(task.history):
        print(f"  [{i}] role={m.role} text={get_message_text(m)}")

    print(f"artifactsCount={len(task.artifacts)}")
    for i, a in enumerate(task.artifacts):
        print(f"  [{i}] name={a.name} text={get_artifact_text(a)}")


@app.callback(invoke_without_command=True)
def main(
    text: str = typer.Option("Hello from 04_Configuration!", help="User message"),
    return_immediately: bool = typer.Option(
        False,
        "--return-immediately/--no-return-immediately",
        help="SendMessageConfiguration: return early in WORKING vs wait for terminal.",
    ),
    history_length: int | None = typer.Option(
        None,
        help="historyLength semantics: unset=None (server default), 0=no limit, >0=limit",
    ),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await create_client(
                card,
                client_config=ClientConfig(
                    supported_protocol_bindings=[
                        card.supported_interfaces[0].protocol_binding
                    ],
                    httpx_client=http,
                ),
            )

            try:
                cfg = SendMessageConfiguration(
                    return_immediately=return_immediately,
                    history_length=history_length,
                )

                request = SendMessageRequest(
                    message=new_text_message(text=text, role=Role.ROLE_USER),
                    configuration=cfg,
                )

                t0 = time.perf_counter()

                [reply] = [r async for r in client.send_message(request)]
                task = reply.task

                dt = time.perf_counter() - t0

                print(
                    "\n"
                    f"returned_after={dt:.2f}s\n"
                    f"return_immediately={return_immediately}\n"
                    f"history_length={history_length}\n"
                )
                print_task(task)

            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
