import asyncio
import os

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, new_text_message
from a2a.types import (
    AgentCard,
    Role,
    SendMessageRequest,
    TaskState,
)
from a2a.utils.errors import VersionNotSupportedError

A2A_BASE_URL: str = os.environ.get("A2A_BASE_URL", "http://localhost:8001")
DEMO_TEXT: str = "Hello from the versioning demo!"

MIN_AGENT_VERSION: str = "0.2.0"


def version_tuple(v: str) -> tuple[int, int, int]:
    core = v.split("-")[0].split("+")[0]
    major, minor, patch = core.split(".")
    return int(major), int(minor), int(patch)


async def send(http: httpx.AsyncClient, card: AgentCard, a2a_version: str) -> None:
    http.headers["A2A-Version"] = a2a_version
    client = await create_client(
        card,
        client_config=ClientConfig(
            supported_protocol_bindings=[card.supported_interfaces[0].protocol_binding],
            httpx_client=http,
            streaming=False,
            polling=False,
        ),
    )
    request = SendMessageRequest(
        message=new_text_message(text=DEMO_TEXT, role=Role.ROLE_USER)
    )
    try:
        task = None
        async for reply in client.send_message(request):
            if reply.HasField("task"):
                task = reply.task
        state = TaskState.Name(task.status.state)
        artifact = get_artifact_text(task.artifacts[0])
        print(f"A2A-Version={a2a_version} -> {state}: {artifact}")
    except VersionNotSupportedError as exc:
        print(f"A2A-Version={a2a_version} -> {type(exc).__name__}: {exc}")


async def _run() -> None:
    async with httpx.AsyncClient(timeout=None) as http:
        card: AgentCard = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
        if version_tuple(card.version) < version_tuple(MIN_AGENT_VERSION):
            print(f"BLOCKED: agent_version={card.version} < min={MIN_AGENT_VERSION}")
            return
        print(f"policy OK: agent_version={card.version} >= min={MIN_AGENT_VERSION}\n")

        await send(http, card, "1.0")
        await send(http, card, "0.3")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
