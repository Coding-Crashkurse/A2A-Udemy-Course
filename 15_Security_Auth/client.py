import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv

from a2a.client import A2AClientError, ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_message_text, new_text_message
from a2a.types import (
    AgentCard,
    Role,
    SendMessageRequest,
)
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

DEMO_TEXT: str = "Hello from streaming demo!"

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID: str = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET: str = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]
A2A_BASE_URL: str = os.environ.get("A2A_BASE_URL", "http://localhost:8001")

TOKEN_URL: str = f"https://{AUTH0_DOMAIN}/oauth/token"


async def fetch_token(http: httpx.AsyncClient) -> str:
    payload: dict[str, Any] = {
        "grant_type": "client_credentials",
        "client_id": AUTH0_CLIENT_ID,
        "client_secret": AUTH0_CLIENT_SECRET,
        "audience": AUTH0_AUDIENCE,
    }

    r = await http.post(TOKEN_URL, json=payload)

    if r.status_code != 200:
        print(f"AUTH0 TOKEN ERROR -> http={r.status_code}")
        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
        else:
            print(r.text)
        raise SystemExit(1)

    data = cast(dict[str, Any], r.json())
    return cast(str, data["access_token"])


def build_config(http: httpx.AsyncClient) -> ClientConfig:
    return ClientConfig(
        supported_protocol_bindings=[TransportProtocol.HTTP_JSON],
        httpx_client=http,
        streaming=False,
        polling=False,
    )


async def demo(http: httpx.AsyncClient, text: str, *, with_token: bool = False) -> None:
    label = "WITH TOKEN" if with_token else "WITHOUT TOKEN"

    if with_token:
        token = await fetch_token(http)
        http.headers["Authorization"] = f"Bearer {token}"

    card: AgentCard = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
    client = await create_client(card, client_config=build_config(http))

    request = SendMessageRequest(
        message=new_text_message(text=text, role=Role.ROLE_USER)
    )

    try:
        async for reply in client.send_message(request):
            if reply.HasField("message"):
                print(f"{label} -> reply: {get_message_text(reply.message)}")
        if not with_token:
            print(f"{label} -> unexpected success (expected 401)")
    except A2AClientError as exc:
        print(f"{label} -> {exc}")


def main() -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=None) as http:
            await demo(http, DEMO_TEXT)
            print("\n--- NOW WITH TOKEN ---\n")
            await demo(http, DEMO_TEXT, with_token=True)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
