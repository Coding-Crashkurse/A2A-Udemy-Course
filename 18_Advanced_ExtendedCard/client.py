import asyncio
import json
import os
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv
from google.protobuf.json_format import MessageToDict

from a2a.client import A2AClientError, ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard, GetExtendedAgentCardRequest
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID: str = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET: str = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]

A2A_BASE_URL: str = os.environ.get("A2A_BASE_URL", "http://localhost:8001")

TOKEN_URL: str = f"https://{AUTH0_DOMAIN}/oauth/token"


def _dump(card: AgentCard) -> str:
    return json.dumps(
        MessageToDict(card, preserving_proto_field_name=True),
        indent=2,
        ensure_ascii=False,
    )


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
        print(json.dumps(r.json(), indent=2) if "application/json" in ct else r.text)
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


async def main() -> None:
    async with httpx.AsyncClient(timeout=15.0) as http:
        print("\n=== 1) PUBLIC AGENT CARD (no auth) ===")
        public_card = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
        print(_dump(public_card))

        client = await create_client(public_card, client_config=build_config(http))

        print("\n=== 2) EXTENDED AGENT CARD (WITHOUT TOKEN) ===")
        try:
            await client.get_extended_agent_card(GetExtendedAgentCardRequest())
            print("Unexpected success (expected 401)")
        except A2AClientError as exc:
            print(f"Rejected as expected -> {exc}")

        print("\n=== 3) AUTHENTICATE (CLIENT CREDENTIALS) ===")
        token = await fetch_token(http)
        http.headers["Authorization"] = f"Bearer {token}"
        print("Token received. (not printing token)")

        print("\n=== 4) EXTENDED AGENT CARD (WITH TOKEN) ===")
        extended_card = await client.get_extended_agent_card(GetExtendedAgentCardRequest())
        print(_dump(extended_card))


if __name__ == "__main__":
    asyncio.run(main())
