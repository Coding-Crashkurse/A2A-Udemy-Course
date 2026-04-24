import os
from pathlib import Path
from typing import Any, Literal, cast

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
    SecurityScheme,
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

EXTENDED_CARD_PATH_V03 = "/v1/card"
EXTENDED_CARD_PATH_V10 = "/v1/extendedAgentCard"

Mode = Literal["legacy", "v1"]


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


def version_not_supported(requested: str, *, supported: list[str]) -> JSONResponse:
    return problem(
        400,
        "https://a2a-protocol.org/errors/version-not-supported",
        "Protocol Version Not Supported",
        f"The requested A2A protocol version {requested} is not supported by this agent",
        supportedVersions=supported,
        requestedVersion=requested,
    )


def wrong_endpoint_for_version(requested: str, expected_path: str) -> JSONResponse:
    return problem(
        400,
        "https://a2a-protocol.org/errors/version-not-supported",
        "Protocol Version Not Supported",
        f"For A2A-Version {requested}, use {expected_path}",
        requestedVersion=requested,
        expectedPath=expected_path,
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


def _security_schemes() -> tuple[dict[str, SecurityScheme], list[dict[str, list[str]]]]:
    bearer = HTTPAuthSecurityScheme(scheme="Bearer", bearer_format="JWT")
    schemes: dict[str, SecurityScheme] = {"bearer": SecurityScheme(root=bearer)}
    security: list[dict[str, list[str]]] = [{"bearer": []}]
    return schemes, security


def build_public_agent_card(
    *,
    base_url: str,
    agent_version: str,
    label: str,
) -> AgentCard:
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
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
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
        security=security,
        supports_authenticated_extended_card=True,
    )


def build_private_agent_card(
    *,
    base_url: str,
    agent_version: str,
    label: str,
) -> AgentCard:
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
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
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
        security=security,
        supports_authenticated_extended_card=True,
    )


class CardOnlyExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(message="This demo only serves agent cards")

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


def build_app(*, mode: Mode, port: int, agent_version: str, label: str) -> FastAPI:
    base_url = f"http://localhost:{port}"

    if mode == "legacy":
        supported_versions = ["0.3"]
    else:
        supported_versions = ["1.0"]

    public_card = build_public_agent_card(
        base_url=base_url,
        agent_version=agent_version,
        label=label,
    )
    private_card = build_private_agent_card(
        base_url=base_url,
        agent_version=agent_version,
        label=label,
    )

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

    extended_card_path = (
        EXTENDED_CARD_PATH_V03 if mode == "legacy" else EXTENDED_CARD_PATH_V10
    )

    @app.get(extended_card_path)
    async def get_extended_agent_card() -> JSONResponse:
        return JSONResponse(
            MessageToDict(private_card, preserving_proto_field_name=True)
        )

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path

        if not path.startswith("/v1/"):
            return await call_next(request)

        requested = request.headers.get("A2A-Version")
        if requested is None:
            return missing_a2a_version()

        if requested not in supported_versions:
            return version_not_supported(requested, supported=supported_versions)

        if path == EXTENDED_CARD_PATH_V03 and requested != "0.3":
            return wrong_endpoint_for_version(requested, EXTENDED_CARD_PATH_V10)

        if path == EXTENDED_CARD_PATH_V10 and requested != "1.0":
            return wrong_endpoint_for_version(requested, EXTENDED_CARD_PATH_V03)

        if path == EXTENDED_CARD_PATH_V03 or path == EXTENDED_CARD_PATH_V10:
            try:
                await verify_bearer_or_raise(request.headers.get("authorization"))
            except PermissionError as e:
                return JSONResponse({"detail": str(e)}, status_code=401)

        return await call_next(request)

    return app


@cli.callback(invoke_without_command=True)
def main(
    mode: Mode = typer.Option(
        "legacy",
        help="legacy (0.3 + /v1/card) | v1 (1.0 + /v1/extendedAgentCard)",
    ),
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
    app = build_app(mode=mode, port=port, agent_version=agent_version, label=label)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
