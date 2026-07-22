from __future__ import annotations

import time
from collections import OrderedDict
from contextlib import asynccontextmanager, contextmanager
from typing import Any


class StageTimer:
    def __init__(self) -> None:
        self._timings: OrderedDict[str, float] = OrderedDict()
        self._stack: list[tuple[str, float]] = []
        self._disabled = False

    @contextmanager
    def track(self, name: str):
        """Sync context manager for timing a code block."""
        if self._disabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._timings[name] = self._timings.get(name, 0.0) + elapsed
            self._stack.append((name, elapsed))

    @asynccontextmanager
    async def atrack(self, name: str):
        """Async context manager for timing an async code block."""
        if self._disabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._timings[name] = self._timings.get(name, 0.0) + elapsed
            self._stack.append((name, elapsed))

    def record(self, name: str, elapsed: float) -> None:
        if not self._disabled:
            self._timings[name] = self._timings.get(name, 0.0) + elapsed

    def summary(self) -> OrderedDict[str, float]:
        return OrderedDict(sorted(self._timings.items(), key=lambda x: x[1], reverse=True))

    def total(self) -> float:
        return sum(self._timings.values())

    def reset(self) -> None:
        self._timings.clear()
        self._stack.clear()

    def disable(self) -> None:
        self._disabled = True

    def enable(self) -> None:
        self._disabled = False

    def as_table(self) -> list[dict[str, Any]]:
        total = self.total()
        rows = []
        for name, elapsed in self.summary().items():
            pct = (elapsed / total * 100) if total > 0 else 0.0
            rows.append({"stage": name, "elapsed_s": round(elapsed, 2), "pct": round(pct, 1)})
        rows.append({"stage": "TOTAL", "elapsed_s": round(total, 2), "pct": 100.0})
        return rows
