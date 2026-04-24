import asyncio
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from a2a.client import ClientConfig, create_client
from a2a.client.card_resolver import A2ACardResolver
from a2a.types import Message, Part, Role, SendMessageRequest

BASE_URL = "http://localhost:8001"

UPLOAD_FILE = Path("upload.txt")
DOWNLOAD_FILE = Path("download.txt")

if not UPLOAD_FILE.exists():
    raise SystemExit(
        "upload.txt fehlt. Bitte vorher anlegen mit Inhalt:\n"
        "I will be uploaded and changed"
    )


def build_uri_message() -> Message:
    return Message(
        role=Role.ROLE_USER,
        message_id=str(uuid.uuid4()),
        parts=[
            Part(
                url="http://127.0.0.1:3000/upload.txt",
                filename="upload.txt",
                media_type="text/plain",
            )
        ],
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

            client = await create_client(
                card,
                client_config=ClientConfig(
                    supported_protocol_bindings=[
                        card.supported_interfaces[0].protocol_binding
                    ],
                    httpx_client=http,
                ),
            )

            request = SendMessageRequest(message=msg)
            task = None
            async for reply in client.send_message(request):
                if reply.HasField("task"):
                    task = reply.task
                    break

            file_part = task.artifacts[0].parts[0]
            download_url = file_part.url

            r = await http.get(download_url)
            r.raise_for_status()
            DOWNLOAD_FILE.write_bytes(r.content)

            await client.close()

        print(DOWNLOAD_FILE.read_text(encoding="utf-8"))

    finally:
        file_server.terminate()
        file_server.wait(timeout=3)


if __name__ == "__main__":
    asyncio.run(main())
