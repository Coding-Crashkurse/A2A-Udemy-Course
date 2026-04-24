import asyncio
import time

import httpx
import typer

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest, Task, TaskState

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


def print_task(task: Task) -> None:
    print(f"taskId={task.id}")
    print(f"contextId={task.context_id}")
    print(f"state={TaskState.Name(task.status.state)}")

    if task.status.message is not None:
        print(f"statusText={get_message_text(task.status.message)}")

    if not task.history:
        print("history=<empty>")
    else:
        print(f"historyCount={len(task.history)}")
        for i, m in enumerate(task.history):
            print(f"  [{i}] role={m.role} text={get_message_text(m)}")

    if not task.artifacts:
        print("artifacts=<empty>")
    else:
        print(f"artifactsCount={len(task.artifacts)}")
        for i, a in enumerate(task.artifacts):
            print(f"  [{i}] name={a.name} meta={dict(a.metadata) if a.metadata else {}}")
            print(f"      text={get_artifact_text(a)}")


@app.callback(invoke_without_command=True)
def main(
    text: str = typer.Option("Hello from 04_Configuration!", help="User message"),
    blocking: bool = typer.Option(
        True,
        "--blocking/--no-blocking",
        help="SendMessageConfiguration: wait for terminal vs return early (working).",
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
                    return_immediately=not blocking,
                    history_length=history_length,
                )

                request = SendMessageRequest(
                    message=new_text_message(text=text, role=Role.ROLE_USER),
                    configuration=cfg,
                )

                t0 = time.perf_counter()

                last_task: Task | None = None
                async for reply in client.send_message(request):
                    if reply.HasField("task"):
                        last_task = reply.task
                        break

                dt = time.perf_counter() - t0

                print(
                    "\n"
                    f"returned_after={dt:.2f}s\n"
                    f"blocking={blocking}\n"
                    f"history_length={history_length}\n"
                )
                if last_task is not None:
                    print_task(last_task)

            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
