import os
from pathlib import Path

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict
from jose import jwt
from jose.exceptions import JWTError

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    UnsupportedOperationError,
)
from a2a.utils import TransportProtocol

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "http://localhost:8001"
AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"]
AUTH0_AUDIENCE = os.environ["AUTH0_AUDIENCE"]

ISSUER = f"https://{AUTH0_DOMAIN}/"
JWKS_URL = f"{ISSUER}.well-known/jwks.json"
JWT_ALGORITHMS = ["RS256"]

EXTENDED_CARD_PATH = "/v1/card"


async def fetch_jwks() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(JWKS_URL)
        r.raise_for_status()
        return r.json()


async def verify_bearer_or_raise(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("Missing Bearer token")

    token = authorization.removeprefix("Bearer ")

    try:
        jwks = await fetch_jwks()

        signing_key_id = jwt.get_unverified_header(token)["kid"]
        jwk_key = next(k for k in jwks["keys"] if k["kid"] == signing_key_id)

        return jwt.decode(
            token,
            jwk_key,
            algorithms=JWT_ALGORITHMS,
            audience=AUTH0_AUDIENCE,
            issuer=ISSUER,
        )
    except (JWTError, KeyError, StopIteration) as e:
        raise PermissionError("Invalid token") from e


def _security_schemes() -> tuple[dict[str, SecurityScheme], list[SecurityRequirement]]:
    bearer = HTTPAuthSecurityScheme(scheme="Bearer", bearer_format="JWT")
    schemes: dict[str, SecurityScheme] = {
        "bearer": SecurityScheme(http_auth_security_scheme=bearer)
    }
    security = [SecurityRequirement(schemes={"bearer": StringList(list=[])})]
    return schemes, security


def build_public_agent_card() -> AgentCard:
    schemes, security = _security_schemes()

    return AgentCard(
        name="AgentCard Demo (Public/Private)",
        description="Public Agent Card is accessible without auth. Extended card requires Bearer JWT.",
        version="0.1.0-demo",
        supported_interfaces=[
            AgentInterface(
                url=BASE_URL,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="public.card.info",
                name="Public Card Info",
                description="Public-facing metadata (no auth).",
                tags=["public", "agent-card", "demo"],
            )
        ],
        security_schemes=schemes,
        security_requirements=security,
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=True
        ),
    )


def build_private_agent_card() -> AgentCard:
    schemes, security = _security_schemes()

    return AgentCard(
        name="AgentCard Demo (Extended)",
        description="Authenticated extended agent card (Bearer JWT).",
        version="0.1.0-demo",
        supported_interfaces=[
            AgentInterface(
                url=BASE_URL,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="public.card.info",
                name="Public Card Info",
                description="Still present here.",
                tags=["public", "agent-card", "demo"],
            ),
            AgentSkill(
                id="private.card.secrets",
                name="Private Card Secrets",
                description="Only visible on extended card.",
                tags=["private", "extended-card", "auth"],
            ),
        ],
        security_schemes=schemes,
        security_requirements=security,
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=True
        ),
    )


class CardOnlyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(message="This demo only serves agent cards")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


public_card = build_public_agent_card()
private_card = build_private_agent_card()

handler = DefaultRequestHandler(
    agent_executor=CardOnlyExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=public_card,
)

app = FastAPI()
for route in create_agent_card_routes(agent_card=public_card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)


@app.get(EXTENDED_CARD_PATH)
async def get_extended_agent_card() -> JSONResponse:
    return JSONResponse(
        MessageToDict(private_card, preserving_proto_field_name=True)
    )


@app.middleware("http")
async def protect_extended_agent_card(request: Request, call_next):
    if request.url.path.rstrip("/") == EXTENDED_CARD_PATH:
        try:
            await verify_bearer_or_raise(request.headers.get("authorization"))
        except PermissionError as e:
            return JSONResponse({"detail": str(e)}, status_code=401)

    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
