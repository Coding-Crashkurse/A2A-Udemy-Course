from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from a2a.client.card_resolver import A2ACardResolver
from a2a.types import AgentCard

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE = os.environ["AUTH0_AUDIENCE"]

A2A_BASE_URL = os.environ.get("A2A_BASE_URL", "http://localhost:8001")

TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"
EXTENDED_CARD_URL = f"{A2A_BASE_URL}/v1/card"


async def fetch_token(http: httpx.AsyncClient) -> str:
    payload = {
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
            print(r.json())
        else:
            print(r.text)
        raise SystemExit(1)

    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("AUTH0 response missing access_token")
    return token


async def main() -> None:
    async with httpx.AsyncClient(timeout=15.0) as http:
        # 1) Public card (SDK resolver)
        print("\n=== 1) PUBLIC AGENT CARD ===")
        public_card = await A2ACardResolver(http, A2A_BASE_URL).get_agent_card()
        print(public_card.model_dump(mode="json", by_alias=True, exclude_none=True))

        # 2) Extended without token (should be 401)
        print("\n=== 2) EXTENDED AGENT CARD (WITHOUT TOKEN) ===")
        r = await http.get(EXTENDED_CARD_URL)
        print(f"HTTP {r.status_code}")
        print(r.text)

        # 3) Authenticate
        print("\n=== 3) AUTHENTICATE (CLIENT CREDENTIALS) ===")
        token = await fetch_token(http)
        print("Token received. (not printing token)")

        # 4) Extended with token (should be 200)
        print("\n=== 4) EXTENDED AGENT CARD (WITH TOKEN) ===")
        r = await http.get(
            EXTENDED_CARD_URL, headers={"Authorization": f"Bearer {token}"}
        )
        print(f"HTTP {r.status_code}")
        r.raise_for_status()

        extended_card = AgentCard.model_validate(r.json())
        print(extended_card.model_dump(mode="json", by_alias=True, exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main())
