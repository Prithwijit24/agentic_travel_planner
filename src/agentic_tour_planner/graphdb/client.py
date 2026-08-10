"""Neo4j client wrapper for the graph database.

Provides a single shared driver instance and a simple query interface.
Every module that talks to Neo4j imports this client — never opens its own driver.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from loguru import logger
from neo4j import Driver, GraphDatabase, Session

from agentic_tour_planner.config.settings import get_settings


class GraphDBClient:
    """Thin wrapper around a shared neo4j.GraphDatabase.driver."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info(f"Neo4j driver initialized: {uri}")

    def run_query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a Cypher query and return results as a list of dicts."""
        params = params or {}
        with self._driver.session() as session:
            result = session.run(cypher, params)
            return [record.data() for record in result]

    def run_write(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a write transaction and return results."""

        def _tx(tx: Session, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            result = tx.run(cypher, params)
            return [record.data() for record in result]

        with self._driver.session() as session:
            return session.execute_write(_tx, cypher, params or {})

    def close(self) -> None:
        self._driver.close()

    def verify_connectivity(self) -> bool:
        try:
            self.run_query("RETURN 1 AS test")
            return True
        except Exception:
            return False


@lru_cache(maxsize=1)
def get_graph_db() -> GraphDBClient:
    settings = get_settings()
    return GraphDBClient(
        uri=getattr(settings, "neo4j_uri", "bolt://localhost:7687"),
        user=getattr(settings, "neo4j_user", "neo4j"),
        password=getattr(settings, "neo4j_password", ""),
    )
