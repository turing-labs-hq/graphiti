import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import Match

from graph_service.config import Settings, get_settings
from graph_service.routers import ingest, retrieve
from graph_service.zep_graphiti import initialize_graphiti

logger = logging.getLogger(__name__)

# /healthcheck stays open so platform health probes (Railway) keep working
# without a credential. Everything else requires the bearer token.
AUTH_EXEMPT_PATHS = {'/healthcheck'}

# The only handlers GRAPHITI_READ_TOKEN reaches: the reads loop chat's brain
# plugin makes. Every other route answers it 403, the writes, the deletes and
# /clear included, and so does any route added later until it is listed here.
# Keyed by the handler the router would run, never by a path string, so no
# spelling of a path can reach a write handler with the read token.
READ_TOKEN_ENDPOINTS = frozenset(
    {
        retrieve.search,
        retrieve.search_nodes,
        retrieve.get_entity_edge,
        retrieve.get_episodes,
    }
)

MIN_READ_TOKEN_CHARS = 32


def read_token_problem(settings: Settings) -> str | None:
    """Why the configured read token cannot be served, or None. The messages
    never carry a token value."""
    read_token = settings.graphiti_read_token
    if not read_token:
        return None
    if not settings.graphiti_token:
        return (
            'GRAPHITI_READ_TOKEN is set but GRAPHITI_TOKEN is not: the API would be open to '
            'anyone, so the read token would restrict nothing'
        )
    if len(read_token) < MIN_READ_TOKEN_CHARS:
        return f'GRAPHITI_READ_TOKEN must be at least {MIN_READ_TOKEN_CHARS} characters'
    if secrets.compare_digest(read_token.encode('utf-8'), settings.graphiti_token.encode('utf-8')):
        return 'GRAPHITI_READ_TOKEN must differ from GRAPHITI_TOKEN'
    return None


def _endpoint_for(request: Request):
    """The handler the router will run for this request (the first full
    match, as Starlette routes), or None when nothing matches in full."""
    for route in request.app.router.routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            return getattr(route, 'endpoint', None)
    return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    problem = read_token_problem(settings)
    if problem:
        raise RuntimeError(f'refusing to start: {problem}')
    if not settings.graphiti_token:
        logger.warning(
            'GRAPHITI_TOKEN is not set - the API is running UNAUTHENTICATED. '
            'Set GRAPHITI_TOKEN in the service environment to require '
            'an "Authorization: Bearer <token>" header on every route except /healthcheck.'
        )
    if settings.graphiti_read_token:
        logger.warning(
            'GRAPHITI_READ_TOKEN is set: it reaches POST /search, POST /search-nodes, '
            'GET /entity-edge/{uuid} and GET /episodes/{group_id} only'
        )
    await initialize_graphiti(settings)
    yield
    # Shutdown
    # No need to close Graphiti here, as it's handled per-request


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def bearer_auth(request: Request, call_next):
    settings = get_settings()
    token = settings.graphiti_token
    read_token = settings.graphiti_read_token
    if request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)
    if read_token_problem(settings):
        # lifespan refuses to start in this state; a request that reaches a
        # process anyway gets nothing.
        return JSONResponse(content={'detail': 'Service misconfigured'}, status_code=503)
    if not token:
        return await call_next(request)
    supplied = request.headers.get('Authorization', '').encode('utf-8')
    if secrets.compare_digest(supplied, f'Bearer {token}'.encode()):
        return await call_next(request)
    if read_token and secrets.compare_digest(supplied, f'Bearer {read_token}'.encode()):
        if _endpoint_for(request) in READ_TOKEN_ENDPOINTS:
            return await call_next(request)
        logger.warning(
            'read token refused: %s %r peer=%s',
            request.method,
            request.url.path,
            request.client.host if request.client else '(unknown)',
        )
        return JSONResponse(content={'detail': 'Forbidden'}, status_code=403)
    return JSONResponse(
        content={'detail': 'Not authenticated'},
        status_code=401,
        headers={'WWW-Authenticate': 'Bearer'},
    )


app.include_router(retrieve.router)
app.include_router(ingest.router)


@app.get('/healthcheck')
async def healthcheck():
    return JSONResponse(content={'status': 'healthy'}, status_code=200)
