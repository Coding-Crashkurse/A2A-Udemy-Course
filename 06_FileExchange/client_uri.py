import asyncio
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import FilePart, FileWithUri, Message, Part, Role
from a2a.utils.parts import get_file_parts

BASE_URL = "http://localhost:8001"

UPLOAD_FILE = Path("upload.txt")
DOWNLOAD_FILE = Path("download.txt")

if not UPLOAD_FILE.exists():
    raise SystemExit(
        "upload.txt fehlt. Bitte vorher anlegen mit Inhalt:\n"
        "I will be uploaded and changed"
    )


def build_uri_message() -> Message:
    upload = FileWithUri(
        uri="http://127.0.0.1:3000/upload.txt",
        name="upload.txt",
        mime_type="text/plain",
    )
    return Message(
        role=Role.user,
        message_id=str(uuid.uuid4()),
        parts=[Part(root=FilePart(file=upload))],
    )


async def main() -> None:
    file_server = subprocess.Popen(
        [sys.executable, "file_server.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        time.sleep(0.2)

        msg = build_uri_message()

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

    finally:
        file_server.terminate()
        file_server.wait(timeout=3)


if __name__ == "__main__":
    asyncio.run(main())
