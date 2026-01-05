from __future__ import annotations

import asyncio
import os
from pathlib import Path
import uuid
from typing import Any, cast

import httpx
import typer
from dotenv import load_dotenv

from a2a.client import ClientConfig, ClientFactory, create_text_message_object
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TransportProtocol,
)
import json

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


def parts_text(parts: list[Part]) -> str:
    # strikt: wir nehmen TextPart (happy path)
    return " ".join(p.root.text for p in parts).strip()


async def fetch_token(http: httpx.AsyncClient) -> str:
    payload: dict[str, Any] = {
        "grant_type": "client_credentials",
        "client_id": AUTH0_CLIENT_ID,
        "client_secret": AUTH0_CLIENT_SECRET,
        "audience": AUTH0_AUDIENCE,
    }

    r = await http.post(TOKEN_URL, json=payload)

    if r.status_code != 200:
        # Auth0-Fehler sichtbar machen
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
        supported_transports=[TransportProtocol.http_json],
        httpx_client=http,
        streaming=True,
        polling=False,
    )


async def demo_fail_without_token(http: httpx.AsyncClient, text: str) -> None:
    # Wir demonstrieren 401 sauber über einen direkten HTTP Call (kein SDK).
    msg = create_text_message_object(content=text)
    body = {"message": msg.model_dump(mode="json", by_alias=True, exclude_none=True)}
    r = await http.post(STREAM_URL, json=body)
    print(f"WITHOUT TOKEN -> http={r.status_code}")
    print(r.text[:300])


async def demo_success_with_token(http: httpx.AsyncClient, text: str) -> None:
    token = await fetch_token(http)
    http.headers["Authorization"] = f"Bearer {token}"

    card: AgentCard = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
    client = await ClientFactory.connect(card, client_config=build_config(http))

    try:
        msg = create_text_message_object(content=text)

        async for task, update in client.send_message(msg):
            # update kann None sein (Snapshot) oder Status/Artifact-Event.
            line = f"state={task.status.state.value}"

            if update is None:
                print(line)
                continue

            # Kein isinstance: wir nehmen das `kind` Discriminator-Feld.
            kind = update.kind
            if kind == "status-update":
                su = cast(TaskStatusUpdateEvent, update)
                if su.status.message is not None:
                    line += f" text={parts_text(su.status.message.parts)}"
                print(line)
                continue

            if kind == "artifact-update":
                au = cast(TaskArtifactUpdateEvent, update)
                line += f" artifact={au.artifact.name} artifactText={parts_text(au.artifact.parts)}"
                print(line)
                continue

    finally:
        await client.close()


@app.callback(invoke_without_command=True)
def main(
    text: str = typer.Option("Hello from streaming demo!", help="Text to send"),
) -> None:
    async def _run() -> None:
        async with httpx.AsyncClient(timeout=None) as http:
            # AgentCard ist öffentlich erreichbar
            r = await http.get(AGENT_CARD_URL)
            r.raise_for_status()

            await demo_fail_without_token(http, text)
            print("\n--- NOW WITH TOKEN ---\n")
            await demo_success_with_token(http, text)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
