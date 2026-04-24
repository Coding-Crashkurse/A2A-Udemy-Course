import asyncio
import os
from pathlib import Path
import time
from typing import Any, cast

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from jose import jwt
from jose.exceptions import JWTError

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    OpenIdConnectSecurityScheme,
    Part,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    TaskState,
)
from a2a.utils import TransportProtocol

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
        task = context.current_task or new_task_from_user_message(context.message)

        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 1/3...")]),
        )
        await asyncio.sleep(1.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 2/3...")]),
        )
        await asyncio.sleep(1.0)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="Working 3/3...")]),
        )
        await asyncio.sleep(1.0)

        await updater.add_artifact(
            [Part(text="Demo artifact text ✅")],
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
        "auth0_oidc": SecurityScheme(open_id_connect_security_scheme=oidc),
        "bearer": SecurityScheme(http_auth_security_scheme=bearer),
    }

    security_requirements = [SecurityRequirement(schemes={"bearer": StringList(list=[])})]

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
        version="0.1.0-demo",
        supported_interfaces=[
            AgentInterface(
                url=BASE_URL,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=skills,
        security_schemes=security_schemes,
        security_requirements=security_requirements,
    )


def build_app() -> FastAPI:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=StreamingDemoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    app = FastAPI()

    # Public AgentCard routes
    for route in create_agent_card_routes(agent_card=card):
        app.router.routes.append(route)

    # Protected A2A routes
    protected = APIRouter(dependencies=[Depends(require_auth)])
    for route in create_rest_routes(request_handler=handler):
        protected.routes.append(route)
    app.include_router(protected)

    return app


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
