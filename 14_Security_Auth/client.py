import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import httpx
import typer
from dotenv import load_dotenv

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import (
    AgentCard,
    Role,
    SendMessageRequest,
    TaskState,
)
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

app = typer.Typer(add_completion=False)

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID: str = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET: str = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]
A2A_BASE_URL: str = os.environ.get("A2A_BASE_URL", "http://localhost:8001")

TOKEN_URL: str = f"https://{AUTH0_DOMAIN}/oauth/token"
AGENT_CARD_URL: str = f"{A2A_BASE_URL}/.well-known/agent-card.json"
STREAM_URL: str = f"{A2A_BASE_URL}/v1/message:stream"


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
        streaming=True,
        polling=False,
    )


async def demo_fail_without_token(http: httpx.AsyncClient, text: str) -> None:
    body = {
        "message": {
            "role": "ROLE_USER",
            "message_id": "demo-msg",
            "parts": [{"text": text}],
        }
    }
    r = await http.post(STREAM_URL, json=body, headers={"A2A-Version": "1.0"})
    print(f"WITHOUT TOKEN -> http={r.status_code}")
    print(r.text[:300])


async def demo_success_with_token(http: httpx.AsyncClient, text: str) -> None:
    token = await fetch_token(http)
    http.headers["Authorization"] = f"Bearer {token}"

    card: AgentCard = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
    client = await create_client(card, client_config=build_config(http))

    try:
        request = SendMessageRequest(
            message=new_text_message(text=text, role=Role.ROLE_USER)
        )

        async for reply in client.send_message(request):
            if reply.HasField("task"):
                t = reply.task
                print(f"state={TaskState.Name(t.status.state)}")
            elif reply.HasField("status_update"):
                su = reply.status_update
                line = f"state={TaskState.Name(su.status.state)}"
                if su.status.HasField("message"):
                    line += f" text={get_message_text(su.status.message)}"
                print(line)
            elif reply.HasField("artifact_update"):
                au = reply.artifact_update
                print(
                    f"artifact={au.artifact.name}"
                    f" artifactText={get_artifact_text(au.artifact)}"
                )

    finally:
        await client.close()


@app.callback(invoke_without_command=True)
def main(
    text: str = typer.Option("Hello from streaming demo!", help="Text to send"),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=None) as http:
            r = await http.get(AGENT_CARD_URL)
            r.raise_for_status()

            await demo_fail_without_token(http, text)
            print("\n--- NOW WITH TOKEN ---\n")
            await demo_success_with_token(http, text)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
