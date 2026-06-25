import logging
import os
from pathlib import Path
from typing import Any

import anyio
import jwt
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    SimpleUser,
)
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection

from a2a.helpers import get_message_text, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    HTTPAuthSecurityScheme,
    OpenIdConnectSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils import TransportProtocol
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

HOST: str = "0.0.0.0"
PORT: int = 8001
BASE_URL: str = f"http://localhost:{PORT}"

AUTH0_DOMAIN: str = os.environ["AUTH0_DOMAIN"]
AUTH0_AUDIENCE: str = os.environ["AUTH0_AUDIENCE"]

ISSUER: str = f"https://{AUTH0_DOMAIN}/"
JWKS_URL: str = f"{ISSUER}.well-known/jwks.json"
ALGORITHMS: list[str] = ["RS256"]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("15_Security_Auth")

PUBLIC_PATHS = {AGENT_CARD_WELL_KNOWN_PATH}


_jwk_client = PyJWKClient(JWKS_URL)


def _verify_token(token: str) -> dict[str, Any]:
    """Verify an Auth0 RS256 token. Blocking (network on cache miss)."""
    signing_key = _jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=ALGORITHMS,
        audience=AUTH0_AUDIENCE,
        issuer=ISSUER,
        leeway=60,
    )


class Auth0Backend(AuthenticationBackend):
    """Verifies the Auth0 bearer token for AuthenticationMiddleware."""

    async def authenticate(
        self, conn: HTTPConnection
    ) -> tuple[AuthCredentials, BaseUser] | None:
        if conn.url.path in PUBLIC_PATHS:
            return None

        header = conn.headers.get("authorization")
        if header is None or not header.startswith("Bearer "):
            raise AuthenticationError("Missing Bearer token")

        token = header.removeprefix("Bearer ").strip()
        try:
            claims = await anyio.to_thread.run_sync(_verify_token, token)
        except PyJWTError as exc:
            raise AuthenticationError("Invalid token") from exc

        scopes = str(claims.get("scope", "")).split()
        return AuthCredentials(scopes), SimpleUser(str(claims.get("sub", "")))


def on_auth_error(conn: HTTPConnection, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=401)


class EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user = context.call_context.user
        log.info(
            "Authenticated caller: user_name=%s is_authenticated=%s",
            user.user_name,
            user.is_authenticated,
        )

        reply = new_text_message(
            f"Authenticated as {user.user_name}. "
            f"You said: {get_message_text(context.message)}"
        )
        await event_queue.enqueue_event(reply)

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

    security_requirements = [
        SecurityRequirement(schemes={"bearer": StringList(list=[])})
    ]

    return AgentCard(
        name="Echo Agent (REST, Auth0 protected)",
        description="Request/response echo protected via Auth0 (RS256 JWT).",
        version="0.1.0-demo",
        supported_interfaces=[
            AgentInterface(
                url=BASE_URL,
                protocol_binding=TransportProtocol.HTTP_JSON,
            ),
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[],
        security_schemes=security_schemes,
        security_requirements=security_requirements,
    )


def build_app() -> FastAPI:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=EchoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    app = FastAPI()

    for route in create_agent_card_routes(agent_card=card):
        app.router.routes.append(route)

    for route in create_rest_routes(request_handler=handler):
        app.router.routes.append(route)

    app.add_middleware(
        AuthenticationMiddleware,
        backend=Auth0Backend(),
        on_error=on_auth_error,
    )

    return app


app = build_app()

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
