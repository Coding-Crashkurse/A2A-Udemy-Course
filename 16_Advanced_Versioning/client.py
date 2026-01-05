from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Literal, cast

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
A2A_BASE_URL_V1: str = os.environ.get("A2A_BASE_URL_V1", "http://localhost:8002")

Target = Literal["legacy", "v1"]


def base_url_for(target: Target) -> str:
    return A2A_BASE_URL if target == "legacy" else A2A_BASE_URL_V1


def extended_card_path_for(protocol_version: str) -> str:
    if protocol_version == "0.3":
        return "/v1/card"
    if protocol_version == "1.0":
        return "/v1/extendedAgentCard"
    raise ValueError(f"unsupported protocol_version: {protocol_version}")


def parse_semver_3(v: str) -> tuple[int, int, int]:
    major_s, minor_s, patch_s = v.split(".")
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
    target: Target = typer.Option("legacy", help="legacy(8001) or v1(8002)"),
    protocol_version: str = typer.Option("0.3", help="A2A-Version header: 0.3 or 1.0"),
    min_agent_version: str = typer.Option(
        "0.2.0",
        help="Client policy: do not talk to agents with AgentCard.version below this (x.y.z).",
    ),
) -> None:
    async def _run() -> None:
        base_url = base_url_for(target).rstrip("/")
        path = extended_card_path_for(protocol_version)
        url = f"{base_url}{path}"

        async with httpx.AsyncClient(timeout=15.0) as http:
            agent_version = await fetch_public_agent_version(http, base_url)
            if parse_semver_3(agent_version) < parse_semver_3(min_agent_version):
                print(
                    f"BLOCKED: agent_version={agent_version} < min_agent_version={min_agent_version} "
                    f"(target={target}, base_url={base_url})"
                )
                return

            token = await fetch_token(http)

            headers = {
                "A2A-Version": protocol_version,
                "Authorization": f"Bearer {token}",
            }
            r = await http.get(url, headers=headers)

            print(
                f"{target=} agent_version={agent_version} {protocol_version=} GET {path} -> HTTP {r.status_code}"
            )
            if r.status_code != 200:
                print(r.text[:800])

    asyncio.run(_run())


if __name__ == "__main__":
    app()
