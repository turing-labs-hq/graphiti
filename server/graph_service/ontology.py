"""Typed extraction ontology for the Turing Labs organizational memory graph.

Mirrors the knowledge-bundle `type` values (client-brain docs/architecture.md §4)
so Layer 1 (bundle) and Layer 2 (graph) speak the same ontology. Passed into
`Graphiti.add_episode(entity_types=..., edge_types=..., edge_type_map=...)` by
the /messages route when ONTOLOGY_ENABLED is true (the default).

How Graphiti uses these:
- Entity/edge model DOCSTRINGS are injected into the extraction prompts as
  classification guidance — they are instructions to the extractor, not schema
  comments. Keep them prescriptive.
- Model FIELDS become extracted attributes on the node/edge. Field names must
  not collide with EntityNode's own fields (uuid, name, group_id, labels,
  created_at, name_embedding, summary, attributes) — graphiti-core's
  validate_entity_types raises at add_episode time on collision.
- EDGE_TYPE_MAP constrains which typed edges may connect which node types,
  keyed on (source_label, target_label). Every node also carries the base
  'Entity' label, so ('Entity', 'Document') matches ANY source node. Pairs not
  listed here still get Graphiti's default untyped relationship extraction —
  the map constrains typed labels, it does not drop facts.
"""

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Entity (node) types — 8, mirroring the bundle ontology
# --------------------------------------------------------------------------


class Person(BaseModel):
    """A real human individual: a named colleague, client contact, stakeholder,
    or candidate. NOT a bot, automation, system, team, mailing list, or job
    title on its own. Prefer the person's full canonical name."""

    role_title: str | None = Field(
        default=None, description="The person's job title or role, if stated"
    )


class Organization(BaseModel):
    """A company, firm, fund, institution, or other organization: clients,
    prospects, partners, vendors, competitors, and Turing Labs itself. NOT a
    team or department inside an organization."""

    org_type: str | None = Field(
        default=None,
        description='One of: client, prospect, partner, vendor, competitor, internal, other',
    )


class Project(BaseModel):
    """A named engagement, workstream, initiative, or deliverable effort with a
    goal and a timeframe — e.g. a client implementation, a migration, a pilot.
    NOT a one-off task or a meeting."""

    status: str | None = Field(
        default=None, description='Current status if stated, e.g. active, paused, done'
    )


class RFP(BaseModel):
    """A request for proposal, tender, bid, or competitive sales opportunity
    that is being pursued or considered. Includes proposal responses."""

    stage: str | None = Field(
        default=None,
        description='Pipeline stage if stated, e.g. qualifying, drafting, submitted, won, lost',
    )


class Document(BaseModel):
    """A named artifact: a deck, contract, proposal, spec, report, spreadsheet,
    transcript, or file. Only extract documents referred to by name or clear
    description — not generic mentions like 'the doc'."""

    url: str | None = Field(
        default=None,
        description='Direct link to the document (web view or storage URL) if one is stated.',
    )
    doc_type: str | None = Field(
        default=None, description='Kind of document if stated, e.g. contract, deck, spec'
    )


class Decision(BaseModel):
    """A concrete decision that was made or explicitly reversed: a chosen
    approach, an approval, a go/no-go, a prioritization call. Must be an
    actual decision, not an open question or a proposal under discussion."""

    status: str | None = Field(
        default=None, description='One of: made, revisited, superseded — if stated'
    )


class Blocker(BaseModel):
    """An impediment, risk, dependency, or issue that is blocking or
    threatening progress on work. Includes open blockers and ones that were
    later resolved (temporal edges capture the resolution)."""

    severity: str | None = Field(
        default=None, description='Severity if stated, e.g. critical, high, medium, low'
    )
    status: str | None = Field(default=None, description='One of: open, mitigated, resolved')


class Capability(BaseModel):
    """A skill, technology, methodology, or service offering — e.g. 'LLM
    evaluation', 'data engineering', 'change management'. Extract only
    capabilities that matter to the work being discussed, not every tool
    name that appears."""

    category: str | None = Field(
        default=None, description='Broad grouping if clear, e.g. engineering, advisory, domain'
    )


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    'Person': Person,
    'Organization': Organization,
    'Project': Project,
    'RFP': RFP,
    'Document': Document,
    'Decision': Decision,
    'Blocker': Blocker,
    'Capability': Capability,
}


# --------------------------------------------------------------------------
# Edge (relationship) types — docstrings guide the extractor; fields become
# edge attributes. Most edges need no attributes.
# --------------------------------------------------------------------------


class WORKS_ON(BaseModel):
    """A person actively works on, leads, or contributes to a project or RFP."""


class WORKS_FOR(BaseModel):
    """A person is employed by or affiliated with an organization."""

    role: str | None = Field(default=None, description='Their role there, if stated')


class DELIVERS_TO(BaseModel):
    """A project or engagement is delivered to / performed for a client
    organization."""


class ISSUED_BY(BaseModel):
    """An RFP or tender was issued or put out by an organization."""


class BIDS_ON(BaseModel):
    """An organization is bidding on, responding to, or pursuing an RFP."""


class DECIDED(BaseModel):
    """A person or organization made a specific decision."""


class AFFECTS(BaseModel):
    """A decision changes the direction, scope, or status of a project or
    organization relationship."""


class BLOCKS(BaseModel):
    """A blocker impedes a project, RFP, or decision from progressing."""


class RESOLVED_BY(BaseModel):
    """A blocker was resolved or mitigated by a person or a decision."""


class MENTIONS_DOCUMENT(BaseModel):
    """Something references, produces, or requests a named document."""


class HAS_CAPABILITY(BaseModel):
    """A person or organization possesses a skill, technology, or service
    capability."""


class REQUIRES_CAPABILITY(BaseModel):
    """A project or RFP requires a specific capability to deliver."""


EDGE_TYPES: dict[str, type[BaseModel]] = {
    'WORKS_ON': WORKS_ON,
    'WORKS_FOR': WORKS_FOR,
    'DELIVERS_TO': DELIVERS_TO,
    'ISSUED_BY': ISSUED_BY,
    'BIDS_ON': BIDS_ON,
    'DECIDED': DECIDED,
    'AFFECTS': AFFECTS,
    'BLOCKS': BLOCKS,
    'RESOLVED_BY': RESOLVED_BY,
    'MENTIONS_DOCUMENT': MENTIONS_DOCUMENT,
    'HAS_CAPABILITY': HAS_CAPABILITY,
    'REQUIRES_CAPABILITY': REQUIRES_CAPABILITY,
}


# (source_label, target_label) → allowed typed edges. 'Entity' matches any
# node type (every node carries the base label). Unlisted pairs fall back to
# Graphiti's default untyped extraction — nothing is dropped.
EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ('Person', 'Project'): ['WORKS_ON'],
    ('Person', 'RFP'): ['WORKS_ON'],
    ('Person', 'Organization'): ['WORKS_FOR'],
    ('Project', 'Organization'): ['DELIVERS_TO'],
    ('RFP', 'Organization'): ['ISSUED_BY'],
    ('Organization', 'RFP'): ['BIDS_ON'],
    ('Person', 'Decision'): ['DECIDED'],
    ('Organization', 'Decision'): ['DECIDED'],
    ('Decision', 'Project'): ['AFFECTS'],
    ('Decision', 'Organization'): ['AFFECTS'],
    ('Blocker', 'Project'): ['BLOCKS'],
    ('Blocker', 'RFP'): ['BLOCKS'],
    ('Blocker', 'Decision'): ['BLOCKS', 'RESOLVED_BY'],
    ('Blocker', 'Person'): ['RESOLVED_BY'],
    ('Entity', 'Document'): ['MENTIONS_DOCUMENT'],
    ('Person', 'Capability'): ['HAS_CAPABILITY'],
    ('Organization', 'Capability'): ['HAS_CAPABILITY'],
    ('Project', 'Capability'): ['REQUIRES_CAPABILITY'],
    ('RFP', 'Capability'): ['REQUIRES_CAPABILITY'],
}
