from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanFeedback, PlanningRequest, PlanningResponse, StoredPlanRecord


class SQLitePlanStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._initialize()
        self._plan_columns = self._table_columns("plans")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.operations_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    destination TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provider_used TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_feedback (
                    plan_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comments TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _table_columns(self, table_name: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def save_plan(self, request: PlanningRequest, response: PlanningResponse) -> None:
        with self._connect() as conn:
            if "request_payload" in self._plan_columns:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO plans
                    (plan_id, destination, provider_used, model_used, created_at, request_payload, response_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response.plan_id,
                        request.destination,
                        response.provider_used,
                        response.model_used,
                        response.generated_at.isoformat(),
                        request.model_dump_json(),
                        response.model_dump_json(),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO plans
                    (plan_id, destination, created_at, provider_used, model_used, request_json, response_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response.plan_id,
                        request.destination,
                        response.generated_at.isoformat(),
                        response.provider_used,
                        response.model_used,
                        request.model_dump_json(),
                        response.model_dump_json(),
                    ),
                )

    def list_plans(self, limit: int = 20) -> list[StoredPlanRecord]:
        with self._connect() as conn:
            if "request_payload" in self._plan_columns:
                rows = conn.execute(
                    """
                    SELECT plan_id, destination, created_at, provider_used, model_used, request_payload, response_payload
                    FROM plans ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT plan_id, destination, created_at, provider_used, model_used, request_json, response_json
                    FROM plans ORDER BY created_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            StoredPlanRecord(
                plan_id=row[0],
                destination=row[1],
                created_at=datetime.fromisoformat(row[2]),
                provider_used=row[3],
                model_used=row[4],
                request=PlanningRequest.model_validate(json.loads(row[5])),
                response=PlanningResponse.model_validate(json.loads(row[6])),
            )
            for row in rows
        ]

    def save_feedback(self, feedback: PlanFeedback) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plan_feedback VALUES (?, ?, ?, ?)",
                (feedback.plan_id, feedback.rating, feedback.comments, datetime.utcnow().isoformat()),
            )
