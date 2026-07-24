from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from graph_service.dto.common import Message


class SearchQuery(BaseModel):
    group_ids: list[str] | None = Field(
        None, description='The group ids for the memories to search'
    )
    query: str
    max_facts: int = Field(default=10, description='The maximum number of facts to retrieve')
    # Both endpoints of a fact must carry one of these node labels (ontology
    # types, e.g. ["Document"]). Previously accepted-and-silently-DROPPED by
    # this DTO (pydantic extra=ignore) — now wired to SearchFilters.
    entity_types: list[str] | None = Field(
        None, description='Restrict facts to edges whose endpoints carry one of these node labels'
    )
    # Relevance floor on the fused reranker score; 0/None = no floor (legacy).
    min_score: float | None = Field(
        None, description='Minimum fused relevance score for returned facts'
    )


class NodeSearchQuery(BaseModel):
    group_ids: list[str] | None = Field(
        None, description='The group ids for the nodes to search'
    )
    query: str
    max_nodes: int = Field(default=10, description='The maximum number of nodes to retrieve')
    entity_types: list[str] | None = Field(
        None, description='Restrict to nodes carrying one of these labels (e.g. ["Document"])'
    )


class FactResult(BaseModel):
    uuid: str
    name: str
    fact: str
    valid_at: datetime | None
    invalid_at: datetime | None
    created_at: datetime
    expired_at: datetime | None
    score: float | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.astimezone(timezone.utc).isoformat()}


class SearchResults(BaseModel):
    facts: list[FactResult]


class GetMemoryRequest(BaseModel):
    group_id: str = Field(..., description='The group id of the memory to get')
    max_facts: int = Field(default=10, description='The maximum number of facts to retrieve')
    center_node_uuid: str | None = Field(
        ..., description='The uuid of the node to center the retrieval on'
    )
    messages: list[Message] = Field(
        ..., description='The messages to build the retrieval query from '
    )


class GetMemoryResponse(BaseModel):
    facts: list[FactResult] = Field(..., description='The facts that were retrieved from the graph')


class NodeResult(BaseModel):
    uuid: str
    name: str
    summary: str
    labels: list[str]
    group_id: str
    attributes: dict[str, Any]
    score: float | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.astimezone(timezone.utc).isoformat()}


class NodeSearchResults(BaseModel):
    nodes: list[NodeResult]
