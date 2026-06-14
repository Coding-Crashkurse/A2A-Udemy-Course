import os
from pathlib import Path
from typing import Any, cast

import httpx
import typer
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
cli = typer.Typer(add_completion=False)

AUTH0_DOMAIN = os.environ["AUTH0_DOMAIN"]
AUTH0_AUDIENCE = os.environ["AUTH0_AUDIENCE"]

ISSUER = f"https://{AUTH0_DOMAIN}/"
JWKS_URL = f"{ISSUER}.well-known/jwks.json"
JWT_ALGORITHMS = ["RS256"]

EXTENDED_CARD_PATH = "/v1/extendedAgentCard"
SUPPORTED_PROTOCOL_VERSION = "1.0"


def problem(
    status: int, type_: str, title: str, detail: str, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status,
        "detail": detail,
    }
    body.update(extra)
    return JSONResponse(
        status_code=status, media_type="application/problem+json", content=body
    )


def missing_a2a_version() -> JSONResponse:
    return problem(
        400,
        "https://a2a-protocol.org/errors/version-not-supported",
        "Protocol Version Not Supported",
        "Missing required A2A-Version header",
        header="A2A-Version",
    )


def version_not_supported(requested: str) -> JSONResponse:
    return problem(
        400,
        "https://a2a-protocol.org/errors/version-not-supported",
        "Protocol Version Not Supported",
        f"The requested A2A protocol version {requested} is not supported by this agent",
        supportedVersions=[SUPPORTED_PROTOCOL_VERSION],
        requestedVersion=requested,
    )


async def fetch_jwks() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get(JWKS_URL)
        r.raise_for_status()
        return cast(dict[str, Any], r.json())


async def verify_bearer_or_raise(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("Missing Bearer token")

    token = authorization.removeprefix("Bearer ").strip()

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


def build_public_agent_card(*, base_url: str, agent_version: str, label: str) -> AgentCard:
    schemes, security = _security_schemes()
    return AgentCard(
        name=f"AgentCard Versioning Demo ({label})",
        description=f"Public card open. Extended card protected. ({label})",
        version=agent_version,
        supported_interfaces=[
            AgentInterface(
                url=base_url,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=True
        ),
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
    )


def build_private_agent_card(*, base_url: str, agent_version: str, label: str) -> AgentCard:
    schemes, security = _security_schemes()
    return AgentCard(
        name=f"AgentCard Versioning Demo (Extended, {label})",
        description=f"Extended agent card. Requires Bearer JWT. ({label})",
        version=agent_version,
        supported_interfaces=[
            AgentInterface(
                url=base_url,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        capabilities=AgentCapabilities(
            streaming=False, push_notifications=False, extended_agent_card=True
        ),
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
    )


class CardOnlyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(message="This demo only serves agent cards")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def build_app(*, port: int, agent_version: str, label: str) -> FastAPI:
    base_url = f"http://localhost:{port}"

    public_card = build_public_agent_card(
        base_url=base_url, agent_version=agent_version, label=label
    )
    private_card = build_private_agent_card(
        base_url=base_url, agent_version=agent_version, label=label
    )

    handler = DefaultRequestHandler(
        agent_executor=CardOnlyExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=public_card,
    )

    app = FastAPI()

    # Custom extended-card route MUST be registered before the SDK rest routes,
    # since create_rest_routes adds a catch-all Mount(path="/{tenant}") that
    # would otherwise intercept /v1/extendedAgentCard.
    @app.get(EXTENDED_CARD_PATH)
    async def get_extended_agent_card() -> JSONResponse:
        return JSONResponse(
            MessageToDict(private_card, preserving_proto_field_name=True)
        )

    for route in create_agent_card_routes(agent_card=public_card):
        app.router.routes.append(route)
    for route in create_rest_routes(request_handler=handler):
        app.router.routes.append(route)

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path

        if not path.startswith("/v1/"):
            return await call_next(request)

        requested = request.headers.get("A2A-Version")
        if requested is None:
            return missing_a2a_version()

        if requested != SUPPORTED_PROTOCOL_VERSION:
            return version_not_supported(requested)

        if path == EXTENDED_CARD_PATH:
            try:
                await verify_bearer_or_raise(request.headers.get("authorization"))
            except PermissionError as e:
                return JSONResponse({"detail": str(e)}, status_code=401)

        return await call_next(request)

    return app


@cli.callback(invoke_without_command=True)
def main(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8001),
    agent_version: str = typer.Option(
        "0.1.0",
        help="AgentCard.version MUST be semver x.y.z (client compares it).",
    ),
    label: str = typer.Option(
        "demo",
        help="Free label shown in name/description (not used for version checks).",
    ),
) -> None:
    app = build_app(port=port, agent_version=agent_version, label=label)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
