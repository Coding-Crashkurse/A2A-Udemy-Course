from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
import uuid
from typing import Any, cast

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from jose import jwt
from jose.exceptions import JWTError

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.rest.rest_adapter import RESTAdapter
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    HTTPAuthSecurityScheme,
    OpenIdConnectSecurityScheme,
    Part,
    Role,
    SecurityScheme,
    TaskState,
    TextPart,
    TransportProtocol,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from a2a.utils import new_task

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

HOST: str = "0.0.0.0"
PORT: int = 8001
BASE_URL: str = f"http://localhost:{PORT}"

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]

ISSUER: str = f"https://{AUTH0_DOMAIN}/"
JWKS_URL: str = f"{ISSUER}.well-known/jwks.json"
ALGORITHMS: list[str] = ["RS256"]

_JWKS_CACHE: dict[str, Any] | None = None
_JWKS_CACHE_TS: float = 0.0
_JWKS_TTL_S: float = 3600.0


async def _get_jwks() -> dict[str, Any]:
    global _JWKS_CACHE, _JWKS_CACHE_TS
    now = time.time()
    if _JWKS_CACHE is not None and (now - _JWKS_CACHE_TS) < _JWKS_TTL_S:
        return _JWKS_CACHE

    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(JWKS_URL)
        r.raise_for_status()
        _JWKS_CACHE = cast(dict[str, Any], r.json())
        _JWKS_CACHE_TS = now
        return _JWKS_CACHE


async def require_auth(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    Validiert Auth0 RS256 JWT lokal:
      - Bearer Header vorhanden
      - kid -> JWKS key
      - Signature + iss + aud + exp
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token: str = authorization.removeprefix("Bearer ").strip()
    jwks: dict[str, Any] = await _get_jwks()

    try:
        header: dict[str, Any] = cast(dict[str, Any], jwt.get_unverified_header(token))
        kid: str | None = cast(str | None, header.get("kid"))
        if kid is None:
            raise HTTPException(status_code=401, detail="Token missing kid")

        keys_any: Any = jwks.get("keys", [])
        keys: list[dict[str, Any]] = cast(list[dict[str, Any]], keys_any)

        key: dict[str, Any] | None = next(
            (k for k in keys if k.get("kid") == kid), None
        )
        if key is None:
            raise HTTPException(status_code=401, detail="Unknown signing key (kid)")

        payload: dict[str, Any] = cast(
            dict[str, Any],
            jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=AUTH0_AUDIENCE,
                issuer=ISSUER,
            ),
        )
        return payload

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


class StreamingDemoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task(context.message)

        # Initial snapshot
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 1/3..."))]),
        )
        await asyncio.sleep(1.0)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 2/3..."))]),
        )
        await asyncio.sleep(1.0)

        await updater.update_status(
            TaskState.working,
            updater.new_agent_message([Part(root=TextPart(text="Working 3/3..."))]),
        )
        await asyncio.sleep(1.0)

        await updater.add_artifact(
            [Part(root=TextPart(text="Demo artifact text ✅"))],
            name="result.txt",
        )

        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def build_agent_card() -> AgentCard:
    oidc = OpenIdConnectSecurityScheme(
        open_id_connect_url=f"{ISSUER}.well-known/openid-configuration"
    )
    bearer = HTTPAuthSecurityScheme(scheme="Bearer", bearer_format="JWT")

    security_schemes: dict[str, SecurityScheme] = {
        "auth0_oidc": SecurityScheme(root=oidc),
        "bearer": SecurityScheme(root=bearer),
    }

    # Ohne permissions/scopes: Requirement ist nur "bearer"
    security: list[dict[str, list[str]]] = [{"bearer": []}]

    skills: list[AgentSkill] = [
        AgentSkill(
            id="demo.streaming.echo",
            name="Streaming Echo Demo",
            description="Streams 3 progress updates and returns one artifact.",
            tags=["demo", "streaming", "sse"],
            examples=["Hello from streaming demo!"],
            input_modes=["text/plain"],
            output_modes=["text/plain"],
        )
    ]

    return AgentCard(
        name="Streaming Demo Agent (REST + SSE, Auth0 protected)",
        description="SSE streaming demo protected via Auth0 (RS256 JWT).",
        url=BASE_URL,
        version="0.1.0-demo",
        protocol_version="0.3.0",
        preferred_transport=TransportProtocol.http_json,
        additional_interfaces=[],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=skills,
        security_schemes=security_schemes,
        security=security,
    )


def build_app() -> FastAPI:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=StreamingDemoExecutor(),
        task_store=InMemoryTaskStore(),
    )

    adapter = RESTAdapter(agent_card=card, http_handler=handler)

    app = FastAPI()

    # 1) Protected A2A routes
    protected = APIRouter(dependencies=[Depends(require_auth)])
    for (path, method), callback in adapter.routes().items():
        protected.add_api_route(path, callback, methods=[method])
    app.include_router(protected)

    # 2) Public AgentCard
    @app.get(AGENT_CARD_WELL_KNOWN_PATH)
    async def get_agent_card(request: Request) -> JSONResponse:
        c = await adapter.handle_get_agent_card(request)
        return JSONResponse(c)

    return app


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
