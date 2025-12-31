import asyncio
import base64
import uuid
from pathlib import Path

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import FilePart, FileWithBytes, FileWithUri, Message, Part, Role
from a2a.utils.parts import get_file_parts

BASE_URL = "http://localhost:8001"

UPLOAD_FILE = Path("upload.txt")
DOWNLOAD_FILE = Path("download.txt")

if not UPLOAD_FILE.exists():
    raise SystemExit(
        "upload.txt fehlt. Bitte vorher anlegen mit Inhalt:\n"
        "I will be uploaded and changed"
    )


def build_inline_message(raw: bytes) -> Message:
    b64 = base64.b64encode(raw).decode("ascii")
    upload = FileWithBytes(bytes=b64, name="upload.txt", mime_type="text/plain")
    return Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        parts=[Part(root=FilePart(file=upload))],
    )


async def main() -> None:
    raw = UPLOAD_FILE.read_bytes()
    msg = build_inline_message(raw)

    async with httpx.AsyncClient(timeout=30) as http:
        card = await A2ACardResolver(http, BASE_URL).get_agent_card()

        client = await ClientFactory.connect(
            card,
            client_config=ClientConfig(
                supported_transports=[card.preferred_transport],
                httpx_client=http,
            ),
        )

        it = client.send_message(msg)
        task, _update = await anext(it)
        await it.aclose()

        file_out = get_file_parts(task.artifacts[0].parts)[0]
        file_out = FileWithUri(**file_out.model_dump())

        r = await http.get(file_out.uri)
        r.raise_for_status()
        DOWNLOAD_FILE.write_bytes(r.content)

        await client.close()

    print(DOWNLOAD_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
