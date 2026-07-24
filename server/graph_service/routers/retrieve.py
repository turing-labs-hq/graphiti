from datetime import datetime, timezone

from fastapi import APIRouter, status

from graphiti_core.search.search_config_recipes import (  # type: ignore
    EDGE_HYBRID_SEARCH_RRF,
    NODE_HYBRID_SEARCH_RRF,
)
from graphiti_core.search.search_filters import SearchFilters  # type: ignore

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


@router.post('/search', status_code=status.HTTP_200_OK)
async def search(query: SearchQuery, graphiti: ZepGraphitiDep):
    # search_() (not search()) so we get reranker scores back, can honor a
    # relevance floor, and can apply the label filter the old DTO silently
    # dropped. Deep-copy the recipe — never mutate the module-level singleton.
    config = EDGE_HYBRID_SEARCH_RRF.model_copy(deep=True)
    config.limit = query.max_facts
    if query.min_score is not None:
        config.reranker_min_score = query.min_score
    search_filter = (
        SearchFilters(node_labels=query.entity_types) if query.entity_types else SearchFilters()
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
    name/summary/labels/attributes, which the edge-only /search cannot."""
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
