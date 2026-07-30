import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from functools import partial

from fastapi import APIRouter, FastAPI, status
from graphiti_core.nodes import EpisodeType  # type: ignore
from graphiti_core.utils.maintenance.graph_data_operations import clear_data  # type: ignore

from graph_service.config import get_settings
from graph_service.dto import AddEntityNodeRequest, AddMessagesRequest, Message, Result
from graph_service.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES, GLOSSARY
from graph_service.zep_graphiti import ZepGraphitiDep

logger = logging.getLogger(__name__)


class AsyncWorker:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.task = None

    async def worker(self):
        while True:
            label = '?'
            try:
                label, job = await self.queue.get()
                print(f'Got a job: (size of remaining queue: {self.queue.qsize()})')
                logger.info(
                    'Ingest job started: %s (remaining queue: %s)', label, self.queue.qsize()
                )
                timeout = get_settings().ingest_job_timeout_seconds
                await asyncio.wait_for(job(), timeout if timeout > 0 else None)
                logger.info(
                    'Ingest job completed: %s (remaining queue: %s)', label, self.queue.qsize()
                )
            except asyncio.CancelledError:
                break
            except TimeoutError:
                # asyncio.TimeoutError is the builtin TimeoutError on >=3.11.
                # wait_for has cancelled the hung coroutine. Without this
                # watchdog, one non-returning await — e.g. a DB read blocking
                # forever (FalkorDB runs TIMEOUT=0 and redis-py's default
                # socket_timeout is None) — froze the whole serial queue with
                # zero log output (observed 2026-07-29 at queue depth 44 and
                # 2026-07-30 at depth 6). Episode uuids are deterministic, so
                # the aborted job re-runs safely on the next sync.
                logger.error(
                    'Ingest job TIMED OUT after %ss: %s (remaining queue: %s) — '
                    'cancelled, continuing with next job',
                    get_settings().ingest_job_timeout_seconds,
                    label,
                    self.queue.qsize(),
                )
            except Exception:
                # A failed job must never kill the worker: before this guard, the
                # first exception escaped the loop and every later queued job was
                # accepted (202) but silently never processed (upstream #566/#1574).
                logger.exception(
                    'Ingest job failed: %s (remaining queue: %s) — continuing with next job',
                    label,
                    self.queue.qsize(),
                )

    async def start(self):
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            # Without suppress, the CancelledError re-raises through lifespan
            # teardown and pollutes shutdown logs.
            with suppress(asyncio.CancelledError):
                await self.task
        while not self.queue.empty():
            self.queue.get_nowait()


async_worker = AsyncWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await async_worker.start()
    yield
    await async_worker.stop()


router = APIRouter(lifespan=lifespan)


@router.post('/messages', status_code=status.HTTP_202_ACCEPTED)
async def add_messages(
    request: AddMessagesRequest,
    graphiti: ZepGraphitiDep,
):
    async def add_messages_task(m: Message):
        # Only wrap the body as 'role(role_type): content' when a real speaker
        # role is supplied. The unconditional wrapper turned non-dialogue
        # payloads into fake dialogue — the message-extraction prompt reads the
        # text before the first colon as the SPEAKER, minting pseudo-speaker
        # entities (e.g. 'knowledge-bundle', 'call-transcript') on every episode.
        if m.role:
            episode_body = f'{m.role}({m.role_type}): {m.content}'
        else:
            episode_body = m.content
        # Typed ontology (graph_service/ontology.py): constrains extraction to
        # the shared bundle/graph node + edge types. ONTOLOGY_ENABLED=false
        # reverts to untyped extraction without a rollback build.
        settings = get_settings()
        ontology_on = settings.ontology_enabled
        # The domain glossary reaches BOTH the node and edge extraction prompts
        # (type docstrings reach neither the edge extractor nor each other), so
        # it is where cross-cutting term disambiguation belongs.
        await graphiti.add_episode(
            uuid=m.uuid,
            group_id=request.group_id,
            name=m.name,
            episode_body=episode_body,
            reference_time=m.timestamp,
            source=EpisodeType.from_str(m.source),
            source_description=m.source_description,
            entity_types=ENTITY_TYPES if ontology_on else None,
            edge_types=EDGE_TYPES if ontology_on else None,
            edge_type_map=EDGE_TYPE_MAP if ontology_on else None,
            custom_extraction_instructions=GLOSSARY if settings.glossary_enabled else None,
        )

    for m in request.messages:
        # Label the job so the worker can name what it is running — a stalled
        # or timed-out job is otherwise anonymous in the logs.
        label = f'{request.group_id}/{m.uuid or m.name}'
        await async_worker.queue.put((label, partial(add_messages_task, m)))

    return Result(message='Messages added to processing queue', success=True)


@router.post('/entity-node', status_code=status.HTTP_201_CREATED)
async def add_entity_node(
    request: AddEntityNodeRequest,
    graphiti: ZepGraphitiDep,
):
    node = await graphiti.save_entity_node(
        uuid=request.uuid,
        group_id=request.group_id,
        name=request.name,
        summary=request.summary,
    )
    return node


@router.delete('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def delete_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_entity_edge(uuid)
    return Result(message='Entity Edge deleted', success=True)


@router.delete('/group/{group_id}', status_code=status.HTTP_200_OK)
async def delete_group(group_id: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_group(group_id)
    return Result(message='Group deleted', success=True)


@router.delete('/episode/{uuid}', status_code=status.HTTP_200_OK)
async def delete_episode(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_episodic_node(uuid)
    return Result(message='Episode deleted', success=True)


@router.post('/clear', status_code=status.HTTP_200_OK)
async def clear(
    graphiti: ZepGraphitiDep,
):
    await clear_data(graphiti.driver)
    await graphiti.build_indices_and_constraints()
    return Result(message='Graph cleared', success=True)
