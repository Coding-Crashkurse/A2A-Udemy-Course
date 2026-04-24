from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Query
from google.protobuf.json_format import MessageToDict

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    ListTasksRequest,
    ListTasksResponse,
    Part,
    Task,
    TaskState,
)
from a2a.utils import TransportProtocol

try:
    from a2a.server.tasks import TaskStore
except Exception:
    from a2a.server.tasks.task_store import TaskStore

try:
    from a2a.server.context import ServerCallContext
except Exception:
    ServerCallContext = Any


HOST = "localhost"
PORT = 8001
BASE_URL = f"http://{HOST}:{PORT}"

DURATION_SECONDS = 30.0
PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("08_ListTasks")


class InspectableInMemoryTaskStore(TaskStore):
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._created_order: list[str] = []
        self._created_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def save(self, task: Task, context: ServerCallContext | None = None) -> None:
        async with self._lock:
            is_new = task.id not in self._tasks
            self._tasks[task.id] = task
            if is_new:
                self._created_order.append(task.id)
                self._created_at[task.id] = time.time()

    async def delete(
        self, task_id: str, context: ServerCallContext | None = None
    ) -> None:
        async with self._lock:
            self._tasks.pop(task_id, None)

    async def list(
        self,
        params: ListTasksRequest,
        context: ServerCallContext | None = None,
    ) -> ListTasksResponse:
        async with self._lock:
            return ListTasksResponse(
                tasks=[self._tasks[tid] for tid in self._created_order if tid in self._tasks]
            )

    async def list_snapshot(
        self,
        *,
        context_id: str | None,
        status: str | None,
        include_artifacts: bool,
        page_size: int,
        page_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            offset = int(page_token) if page_token else 0
        except ValueError:
            offset = 0

        status_norm = status.strip().upper() if status else None

        async with self._lock:
            ids = list(self._created_order)

            filtered: list[Task] = []
            for tid in ids:
                t = self._tasks.get(tid)
                if t is None:
                    continue
                if context_id and t.context_id != context_id:
                    continue
                if status_norm:
                    state_name = TaskState.Name(t.status.state) if t.status else ""
                    short = state_name.replace("TASK_STATE_", "")
                    if short != status_norm:
                        continue
                filtered.append(t)

            total = len(filtered)
            page = filtered[offset : offset + page_size]
            next_token = (
                str(offset + page_size) if (offset + page_size) < total else None
            )

            out: list[dict[str, Any]] = []
            for t in page:
                d = MessageToDict(t, preserving_proto_field_name=True)
                d.pop("history", None)
                if not include_artifacts:
                    d.pop("artifacts", None)
                out.append(d)

            return out, next_token


class FireAndForget30sExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)

        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message(
                [Part(text="Accepted. Working... (~30s)")]
            ),
        )

        for i in range(1, 4):
            await asyncio.sleep(DURATION_SECONDS / 3.0)
            await updater.update_status(
                TaskState.TASK_STATE_WORKING,
                updater.new_agent_message([Part(text=f"Progress {i}/3")]),
            )

        await updater.add_artifact(
            [Part(text="Result payload for ListTasks demo")],
            name="result.txt",
        )

        await updater.complete(
            updater.new_agent_message([Part(text="Done.")])
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return


card = AgentCard(
    name="08 ListTasks Demo Agent (REST)",
    description="Creates long-running tasks and implements GET /v1/tasks for ListTasks.",
    version="0.8.0-demo",
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
)

task_store = InspectableInMemoryTaskStore()

handler = DefaultRequestHandler(
    agent_executor=FireAndForget30sExecutor(),
    task_store=task_store,
    agent_card=card,
)

app: FastAPI = FastAPI()
for route in create_agent_card_routes(agent_card=card):
    app.router.routes.append(route)
for route in create_rest_routes(request_handler=handler):
    app.router.routes.append(route)


@app.get("/v1/tasks")
async def list_tasks(
    context_id: str | None = Query(default=None, alias="contextId"),
    status: str | None = Query(default=None, alias="status"),
    include_artifacts: bool = Query(default=False, alias="includeArtifacts"),
    page_size: int = Query(
        default=PAGE_SIZE_DEFAULT, alias="pageSize", ge=1, le=PAGE_SIZE_MAX
    ),
    page_token: str | None = Query(default=None, alias="pageToken"),
) -> dict[str, Any]:
    tasks, next_token = await task_store.list_snapshot(
        context_id=context_id,
        status=status,
        include_artifacts=include_artifacts,
        page_size=page_size,
        page_token=page_token,
    )
    return {"tasks": tasks, "nextPageToken": next_token}


def _move_route_to_front(app_: FastAPI, path: str, method: str, endpoint) -> None:
    routes = app_.router.routes
    for i, r in enumerate(routes):
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            if getattr(r, "endpoint", None) is endpoint:
                routes.insert(0, routes.pop(i))
                return


_move_route_to_front(app, "/v1/tasks", "GET", list_tasks)


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
