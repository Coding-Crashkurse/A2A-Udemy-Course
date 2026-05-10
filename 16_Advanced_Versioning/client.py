import asyncio
import os
from pathlib import Path
from typing import Any, cast

import httpx
import typer
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
app = typer.Typer(add_completion=False)

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_CLIENT_ID: str = os.environ["AUTH0_CLIENT_ID"]
AUTH0_CLIENT_SECRET: str = os.environ["AUTH0_CLIENT_SECRET"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]

TOKEN_URL: str = f"https://{AUTH0_DOMAIN}/oauth/token"

A2A_BASE_URL: str = os.environ.get("A2A_BASE_URL", "http://localhost:8001")
EXTENDED_CARD_PATH = "/v1/extendedAgentCard"
PROTOCOL_VERSION = "1.0"


def parse_semver_3(v: str) -> tuple[int, int, int]:
    core = v.split("-", 1)[0].split("+", 1)[0]
    major_s, minor_s, patch_s = core.split(".")
    return int(major_s), int(minor_s), int(patch_s)


async def fetch_public_agent_version(http: httpx.AsyncClient, base_url: str) -> str:
    url = base_url.rstrip("/") + "/.well-known/agent-card.json"
    r = await http.get(url)
    r.raise_for_status()
    data = cast(dict[str, Any], r.json())
    v = data.get("version")
    if not isinstance(v, str) or not v:
        raise RuntimeError("AgentCard.version missing")
    return v


async def fetch_token(http: httpx.AsyncClient) -> str:
    payload: dict[str, Any] = {
        "grant_type": "client_credentials",
        "client_id": AUTH0_CLIENT_ID,
        "client_secret": AUTH0_CLIENT_SECRET,
        "audience": AUTH0_AUDIENCE,
    }
    r = await http.post(TOKEN_URL, json=payload)
    r.raise_for_status()

    data = cast(dict[str, Any], r.json())
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("AUTH0 response missing access_token")
    return token


@app.callback(invoke_without_command=True)
def main(
    base_url: str = typer.Option(
        A2A_BASE_URL, help="Server base URL (default reads $A2A_BASE_URL)."
    ),
    min_agent_version: str = typer.Option(
        "0.2.0",
        help="Client policy: do not talk to agents with AgentCard.version below this (x.y.z).",
    ),
) -> None:
    async def _run() -> None:
        target = base_url.rstrip("/")
        url = f"{target}{EXTENDED_CARD_PATH}"

        async with httpx.AsyncClient(timeout=15.0) as http:
            agent_version = await fetch_public_agent_version(http, target)
            if parse_semver_3(agent_version) < parse_semver_3(min_agent_version):
                print(
                    f"BLOCKED: agent_version={agent_version} < min_agent_version={min_agent_version} "
                    f"(base_url={target})"
                )
                return

            token = await fetch_token(http)

            headers = {
                "A2A-Version": PROTOCOL_VERSION,
                "Authorization": f"Bearer {token}",
            }
            r = await http.get(url, headers=headers)

            print(
                f"agent_version={agent_version} GET {EXTENDED_CARD_PATH} -> HTTP {r.status_code}"
            )
            if r.status_code != 200:
                print(r.text[:800])

    asyncio.run(_run())


if __name__ == "__main__":
    app()
