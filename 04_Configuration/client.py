import asyncio
import time

import httpx
import typer

from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import MessageSendConfiguration, Task
from a2a.utils import get_artifact_text, get_message_text

BASE_URL = "http://localhost:8001"

app = typer.Typer(add_completion=False)


def print_task(task: Task) -> None:
    print(f"taskId={task.id}")
    print(f"contextId={task.context_id}")
    print(f"state={task.status.state.value}")

    if task.status.message is not None:
        print(f"statusText={get_message_text(task.status.message)}")

    if task.history is None:
        print("history=<omitted>")
    elif len(task.history) == 0:
        print("history=<empty>")
    else:
        print(f"historyCount={len(task.history)}")
        for i, m in enumerate(task.history):
            print(f"  [{i}] role={m.role} text={get_message_text(m)}")

    if task.artifacts is None:
        print("artifacts=<omitted>")
    elif len(task.artifacts) == 0:
        print("artifacts=<empty>")
    else:
        print(f"artifactsCount={len(task.artifacts)}")
        for i, a in enumerate(task.artifacts):
            print(f"  [{i}] name={a.name} meta={a.metadata}")
            print(f"      text={get_artifact_text(a)}")


@app.callback(invoke_without_command=True)
def main(
    text: str = typer.Option("Hello from 04_Configuration!", help="User message"),
    blocking: bool = typer.Option(
        True,
        "--blocking/--no-blocking",
        help="MessageSendConfiguration.blocking: wait for terminal vs return early (working).",
    ),
    history_length: int | None = typer.Option(
        None,
        help="historyLength semantics: unset=None (server default), 0=no limit, >0=limit",
    ),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=30) as http:
            card = await A2ACardResolver(http, BASE_URL).get_agent_card()

            client = await ClientFactory.connect(
                card,
                client_config=ClientConfig(
                    supported_transports=[card.preferred_transport],
                    httpx_client=http,
                ),
            )

            try:
                msg = create_text_message_object(content=text)

                cfg = MessageSendConfiguration(
                    blocking=blocking,
                    history_length=history_length,
                )

                t0 = time.perf_counter()

                # Wichtig: SDK liefert (task, update)
                event_iter = client.send_message(msg, configuration=cfg)
                task, _update = await anext(event_iter)
                await event_iter.aclose()

                dt = time.perf_counter() - t0

                print(
                    "\n"
                    f"returned_after={dt:.2f}s\n"
                    f"blocking={blocking}\n"
                    f"history_length={history_length}\n"
                )
                print_task(task)

            finally:
                await client.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
