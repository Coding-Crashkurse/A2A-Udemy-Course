import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path

HOST = "127.0.0.1"
PORT = 3000

UPLOAD_FILE = Path("upload.txt")

app = FastAPI()


@app.get("/upload.txt")
async def upload_txt() -> FileResponse:
    return FileResponse(
        path=UPLOAD_FILE,
        media_type="text/plain",
        filename="upload.txt",
    )


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
