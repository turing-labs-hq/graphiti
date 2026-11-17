"""The fulltext query builders interpolate only allow-listed identifiers and Cypher expressions."""

import pytest

from graphiti_core.driver.driver import GraphProvider
from graphiti_core.graph_queries import get_nodes_query, get_relationships_query

PROVIDERS = [GraphProvider.NEO4J, GraphProvider.FALKORDB, GraphProvider.KUZU]


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('name', ['node_name_and_summary', 'community_name', 'episode_content'])
@pytest.mark.parametrize('query', ['$query', 'node.fulltext_query'])
def test_nodes_query_accepts_known_index_and_expression(provider, name, query):
    cypher = get_nodes_query(name, query, limit=10, provider=provider)
    assert query in cypher


def test_nodes_query_output_unchanged():
    assert (
        get_nodes_query('node_name_and_summary', '$query', 10, GraphProvider.NEO4J)
        == 'CALL db.index.fulltext.queryNodes("node_name_and_summary", $query, {limit: $limit})'
    )
    assert (
        get_nodes_query('episode_content', '$query', 10, GraphProvider.FALKORDB)
        == "CALL db.idx.fulltext.queryNodes('Episodic', $query)"
    )
    assert (
        get_nodes_query('community_name', '$query', 10, GraphProvider.KUZU)
        == "CALL QUERY_FTS_INDEX('Community', 'community_name', $query, TOP := $limit)"
    )


@pytest.mark.parametrize('provider', PROVIDERS)
def test_relationships_query_output_unchanged(provider):
    cypher = get_relationships_query('edge_name_and_fact', limit=10, provider=provider)
    assert '$query' in cypher


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize(
    'name',
    [
        'edge_name_and_fact',  # a relationship index, not a node index
        'unknown_index',
        'node_name_and_summary", $q, {}) MATCH (n) DETACH DELETE n //',
    ],
)
def test_nodes_query_rejects_unknown_index(provider, name):
    with pytest.raises(ValueError):
        get_nodes_query(name, '$query', limit=10, provider=provider)


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize(
    'query',
    [
        "'alice'",
        'alice',
        '$query) MATCH (n) DETACH DELETE n //',
        '$query, {limit: 1}',
        'node.fulltext_query OR 1=1',
        '',
    ],
)
def test_nodes_query_rejects_non_expression_query(provider, query):
    with pytest.raises(ValueError):
        get_nodes_query('node_name_and_summary', query, limit=10, provider=provider)


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('name', ['node_name_and_summary', "edge_name_and_fact') //"])
def test_relationships_query_rejects_unknown_index(provider, name):
    with pytest.raises(ValueError):
        get_relationships_query(name, limit=10, provider=provider)
