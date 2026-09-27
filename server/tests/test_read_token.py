"""GRAPHITI_READ_TOKEN: a second bearer that reaches the four read handlers
loop chat's brain plugin calls, and nothing else.

No database and no network: the graphiti dependency is a fake that records
every call, so a refused request is proven to have run nothing. Settings are
built here with no .env file read, and the lifespan (which connects to the
database) is not run except where a test drives it on purpose.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import graph_service.main as main
from graph_service.config import Settings
from graph_service.zep_graphiti import get_graphiti

FULL = 'full-' + 'f' * 40
READ = 'read-' + 'r' * 40


def _settings(**overrides) -> Settings:
    values = {
        'openai_api_key': 'test-not-a-key',
        'graphiti_token': FULL,
        'graphiti_read_token': READ,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class FakeGraphiti:
    def __init__(self):
        self.calls: list[str] = []
        self.driver = SimpleNamespace()

    async def search_(self, **kwargs):
        self.calls.append('search_')
        return SimpleNamespace(edges=[], edge_reranker_scores=[], nodes=[], node_reranker_scores=[])

    async def get_entity_edge(self, uuid):
        self.calls.append('get_entity_edge')
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            uuid=uuid,
            name='WORKS_ON',
            fact='a fact',
            valid_at=None,
            invalid_at=None,
            created_at=now,
            expired_at=None,
        )

    async def retrieve_episodes(self, **kwargs):
        self.calls.append('retrieve_episodes')
        return []

    async def search(self, **kwargs):
        self.calls.append('search')
        return []

    async def delete_group(self, group_id):
        self.calls.append('delete_group')

    async def delete_entity_edge(self, uuid):
        self.calls.append('delete_entity_edge')

    async def delete_episodic_node(self, uuid):
        self.calls.append('delete_episodic_node')

    async def save_entity_node(self, **kwargs):
        self.calls.append('save_entity_node')
        return {}

    async def build_indices_and_constraints(self):
        self.calls.append('build_indices_and_constraints')


@pytest.fixture
def fake():
    return FakeGraphiti()


@pytest.fixture
def client(monkeypatch, fake):
    return _client(monkeypatch, fake, _settings())


def _client(monkeypatch, fake, settings):
    monkeypatch.setattr(main, 'get_settings', lambda: settings)

    async def _fake_graphiti():
        yield fake

    main.app.dependency_overrides[get_graphiti] = _fake_graphiti
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main.app.dependency_overrides.clear()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


READS = [
    ('POST', '/search', {'query': 'q', 'group_ids': ['internal']}),
    ('POST', '/search-nodes', {'query': 'q', 'group_ids': ['internal']}),
    ('GET', '/entity-edge/0b0e7b2c-0000-4000-8000-000000000000', None),
    ('GET', '/episodes/internal?last_n=1', None),
]

# Every route the read token must not reach, the design's /clear and group
# deletes first. POST /get-memory is a read the brain plugin does not call.
REFUSED = [
    ('POST', '/clear', None),
    ('DELETE', '/group/internal', None),
    ('DELETE', '/entity-edge/0b0e7b2c-0000-4000-8000-000000000000', None),
    ('DELETE', '/episode/0b0e7b2c-0000-4000-8000-000000000000', None),
    ('POST', '/messages', {'group_id': 'internal', 'messages': []}),
    ('POST', '/entity-node', {'uuid': 'u', 'group_id': 'internal', 'name': 'n'}),
    ('POST', '/get-memory', {'group_id': 'internal', 'messages': []}),
    ('GET', '/openapi.json', None),
    ('GET', '/docs', None),
    ('GET', '/search', None),
    ('PUT', '/search', {'query': 'q'}),
    ('POST', '/search/', {'query': 'q'}),
    ('GET', '/nothing-here', None),
]


@pytest.mark.parametrize(('method', 'path', 'body'), READS)
def test_read_token_reaches_the_reads(client, fake, method, path, body):
    answer = client.request(method, path, json=body, headers=_auth(READ))
    assert answer.status_code == 200, answer.text
    assert fake.calls


@pytest.mark.parametrize(('method', 'path', 'body'), REFUSED)
def test_read_token_refused_everywhere_else(client, fake, method, path, body):
    answer = client.request(method, path, json=body, headers=_auth(READ))
    assert answer.status_code == 403, answer.text
    assert answer.json() == {'detail': 'Forbidden'}
    assert fake.calls == []


FULL_ONLY = [
    ('DELETE', '/group/internal', None, 'delete_group'),
    ('DELETE', '/entity-edge/0b0e7b2c-0000-4000-8000-000000000000', None, 'delete_entity_edge'),
    ('DELETE', '/episode/0b0e7b2c-0000-4000-8000-000000000000', None, 'delete_episodic_node'),
    (
        'POST',
        '/entity-node',
        {'uuid': 'u', 'group_id': 'internal', 'name': 'n'},
        'save_entity_node',
    ),
]


@pytest.mark.parametrize(('method', 'path', 'body'), READS)
def test_full_token_still_reads(client, fake, method, path, body):
    answer = client.request(method, path, json=body, headers=_auth(FULL))
    assert answer.status_code == 200, answer.text


@pytest.mark.parametrize(('method', 'path', 'body', 'call'), FULL_ONLY)
def test_full_token_still_writes(client, fake, method, path, body, call):
    answer = client.request(method, path, json=body, headers=_auth(FULL))
    assert answer.status_code in (200, 201), answer.text
    assert fake.calls == [call]


@pytest.mark.parametrize(
    'headers',
    [
        {},
        {'Authorization': READ},
        {'Authorization': f'Bearer {READ}x'},
        {'Authorization': f'Bearer {READ[:-1]}'},
        {'Authorization': 'Bearer '},
        {'Authorization': f'bearer {READ}'},
    ],
)
def test_anything_else_is_401(client, fake, headers):
    answer = client.post('/search', json={'query': 'q'}, headers=headers)
    assert answer.status_code == 401
    assert fake.calls == []


def test_healthcheck_stays_open(client):
    assert client.get('/healthcheck').status_code == 200


def test_unset_read_token_changes_nothing(monkeypatch, fake):
    client = _client(monkeypatch, fake, _settings(graphiti_read_token=None))
    assert client.post('/search', json={'query': 'q'}, headers=_auth(READ)).status_code == 401
    assert client.post('/search', json={'query': 'q'}, headers=_auth(FULL)).status_code == 200


@pytest.mark.parametrize(
    ('overrides', 'reason'),
    [
        ({'graphiti_token': None}, 'GRAPHITI_TOKEN is not'),
        ({'graphiti_read_token': 'short'}, 'at least 32 characters'),
        ({'graphiti_read_token': FULL}, 'must differ'),
    ],
)
def test_misconfigured_read_token_refused(monkeypatch, fake, overrides, reason):
    """Refused at boot, and a request reaching such a process anyway runs
    nothing: without GRAPHITI_TOKEN the API would otherwise be open."""
    settings = _settings(**overrides)
    problem = main.read_token_problem(settings)
    assert problem and reason in problem
    assert READ not in problem and FULL not in problem

    monkeypatch.setattr(main, 'get_settings', lambda: settings)
    with pytest.raises(RuntimeError, match='refusing to start'):
        asyncio.run(main.lifespan(main.app).__aenter__())

    client = _client(monkeypatch, fake, settings)
    for token in (READ, FULL, 'short'):
        answer = client.post('/clear', headers=_auth(token))
        assert answer.status_code == 503
    assert client.get('/healthcheck').status_code == 200
    assert fake.calls == []


def test_every_listed_endpoint_is_a_read():
    """The allowlist names read handlers only, all in the retrieve router."""
    from graph_service.routers import retrieve

    for endpoint in main.READ_TOKEN_ENDPOINTS:
        assert endpoint.__module__ == retrieve.__name__
    assert retrieve.get_memory not in main.READ_TOKEN_ENDPOINTS
