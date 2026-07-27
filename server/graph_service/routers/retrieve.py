from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, status

from graphiti_core.search.search_config_recipes import (  # type: ignore
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_RRF,
)
from graphiti_core.search.search_filters import (  # type: ignore
    ComparisonOperator,
    DateFilter,
    SearchFilters,
)

from graph_service.dto import (
    GetMemoryRequest,
    GetMemoryResponse,
    Message,
    NodeResult,
    NodeSearchQuery,
    NodeSearchResults,
    SearchQuery,
    SearchResults,
)
from graph_service.zep_graphiti import ZepGraphitiDep, get_fact_result_from_edge

router = APIRouter()


def _live_edges_only() -> list[list[DateFilter]]:
    """`(e.expired_at IS NULL)` — the filter that keeps superseded facts out.

    Filter on expired_at ONLY. The two temporal fields are not interchangeable:

    - `expired_at` is the TRANSACTION-time axis, stamped `utc_now()` by
      `resolve_edge_contradictions` when Graphiti supersedes an edge. Non-null
      means exactly "Graphiti considers this fact superseded".
    - `invalid_at` is the EVENT-time axis and is set directly by extraction
      whenever an end date is stated — including future dates, for facts that
      are true right now ("the engagement runs until 2027-01-01"). Filtering on
      it would silently drop the most relevant facts we have.

    One clause, `is_null`, binds no parameter — which also sidesteps the
    upstream OR-group date-parameter collision (getzep/graphiti#1596).
    """
    return [[DateFilter(comparison_operator=ComparisonOperator.is_null)]]


def _changed_within(days: int | None) -> list[list[DateFilter]] | None:
    """`(e.created_at > $created_at_0)` — deliberately ONE clause.

    SearchFilters joins its fragments with ' AND ', one entry per temporal
    field, so cross-field OR ("valid now OR changed recently") is inexpressible
    by construction — a wall, not a knob we chose not to turn. Staying at one
    clause per field also keeps the upstream OR-group parameter-collision bug
    (getzep/graphiti#1596, param key indexed by inner position only)
    unreachable, so no graphiti_core change is needed.

    The cutoff is computed server-side: a client sending a timestamp would be
    trusting its own clock against the graph's.
    """
    if days is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [[DateFilter(date=cutoff, comparison_operator=ComparisonOperator.greater_than)]]


@router.post('/search', status_code=status.HTTP_200_OK)
async def search(query: SearchQuery, graphiti: ZepGraphitiDep):
    # search_() (not search()) so we get reranker scores back, can honor a
    # relevance floor, and can apply the label filter the old DTO silently
    # dropped. Deep-copy the recipe — never mutate the module-level singleton.
    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = query.max_facts
    if query.min_score is not None:
        config.reranker_min_score = query.min_score
    search_filter = SearchFilters(
        node_labels=query.entity_types or None,
        edge_types=query.edge_types or None,
        expired_at=None if query.include_invalidated else _live_edges_only(),
        created_at=_changed_within(query.changed_within_days),
    )
    results = await graphiti.search_(
        query=query.query,
        config=config,
        group_ids=query.group_ids,
        search_filter=search_filter,
    )
    scores = list(results.edge_reranker_scores) + [None] * len(results.edges)
    facts = [
        get_fact_result_from_edge(edge, score=score)
        for edge, score in zip(results.edges, scores, strict=False)
    ]
    return SearchResults(
        facts=facts,
    )


@router.post('/search-nodes', status_code=status.HTTP_200_OK)
async def search_nodes(query: NodeSearchQuery, graphiti: ZepGraphitiDep):
    """Hybrid search over entity NODES (e.g. Document) — returns
    name/summary/labels/attributes, which the edge-only /search cannot.

    No temporal filter here: node_search_filter_query_constructor consumes
    node_labels and nothing else — the four DateFilter fields are edge-only in
    graphiti_core, so `include_invalidated` has no node-side equivalent without
    a core patch. Entity nodes are not superseded the way facts are.
    """
    config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = query.max_nodes
    search_filter = (
        SearchFilters(node_labels=query.entity_types) if query.entity_types else SearchFilters()
    )
    results = await graphiti.search_(
        query=query.query,
        config=config,
        group_ids=query.group_ids,
        search_filter=search_filter,
    )
    scores = list(results.node_reranker_scores) + [None] * len(results.nodes)
    nodes = [
        NodeResult(
            uuid=node.uuid, name=node.name, summary=node.summary,
            labels=list(node.labels or []), group_id=node.group_id,
            attributes={k: v for k, v in (node.attributes or {}).items()
                        if isinstance(v, (str, int, float, bool)) or v is None},
            score=score,
        )
        for node, score in zip(results.nodes, scores, strict=False)
    ]
    return NodeSearchResults(nodes=nodes)


@router.get('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def get_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    entity_edge = await graphiti.get_entity_edge(uuid)
    return get_fact_result_from_edge(entity_edge)


@router.get('/episodes/{group_id}', status_code=status.HTTP_200_OK)
async def get_episodes(group_id: str, last_n: int, graphiti: ZepGraphitiDep):
    episodes = await graphiti.retrieve_episodes(
        group_ids=[group_id], last_n=last_n, reference_time=datetime.now(timezone.utc)
    )
    return episodes


@router.post('/get-memory', status_code=status.HTTP_200_OK)
async def get_memory(
    request: GetMemoryRequest,
    graphiti: ZepGraphitiDep,
):
    combined_query = compose_query_from_messages(request.messages)
    result = await graphiti.search(
        group_ids=[request.group_id],
        query=combined_query,
        num_results=request.max_facts,
    )
    facts = [get_fact_result_from_edge(edge) for edge in result]
    return GetMemoryResponse(facts=facts)


def compose_query_from_messages(messages: list[Message]):
    combined_query = ''
    for message in messages:
        combined_query += f'{message.role_type or ""}({message.role or ""}): {message.content}\n'
    return combined_query
