from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore


class Settings(BaseSettings):
    openai_api_key: str
    openai_base_url: str | None = Field(None)
    model_name: str | None = Field(None)
    embedding_model_name: str | None = Field(None)
    neo4j_uri: str | None = Field(None)
    neo4j_user: str | None = Field(None)
    neo4j_password: str | None = Field(None)
    falkordb_host: str | None = Field(None)
    falkordb_port: int | None = Field(None)
    falkordb_password: str | None = Field(None)
    falkordb_database: str | None = Field(None)
    db_backend: str = Field('neo4j')
    # Bearer token required on every route except /healthcheck. Unset = open
    # (a loud startup warning is logged) so the patch can deploy before the
    # variable exists and auth can be dropped without a rollback build.
    graphiti_token: str | None = Field(None)
    # Typed extraction ontology (graph_service/ontology.py) on /messages.
    # Set ONTOLOGY_ENABLED=false to fall back to untyped extraction without
    # a rollback build.
    ontology_enabled: bool = Field(True)
    # Domain glossary (ontology.GLOSSARY) passed to extraction as
    # custom_extraction_instructions. Independent of the ontology switch —
    # it disambiguates terms, it does not type anything. GLOSSARY_ENABLED=false
    # drops it without a rollback build.
    glossary_enabled: bool = Field(True)

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


@lru_cache
def get_settings():
    return Settings()  # type: ignore[call-arg]


ZepEnvDep = Annotated[Settings, Depends(get_settings)]
