"""
Dependency-aware readiness registry.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from time import perf_counter
from typing import Self

from fastapi import FastAPI


@dataclass(slots=True)
class ReadinessCheckResult:
    """Structured readiness result for one dependency."""

    name: str
    is_healthy: bool
    detail: str
    latency_ms: float | None = None

    @classmethod
    def ok(cls, name: str, detail: str = "ok", latency_ms: float | None = None) -> "Self":
        return cls(name=name, is_healthy=True, detail=detail, latency_ms=latency_ms)

    @classmethod
    def error(
        cls,
        name: str,
        detail: str,
        latency_ms: float | None = None,
    ) -> "Self":
        return cls(name=name, is_healthy=False, detail=detail, latency_ms=latency_ms)

    def as_payload(self, *, include_detail: bool = True) -> dict[str, str | bool | float | None]:
        """Serialize the result for JSON responses."""
        payload: dict[str, str | bool | float | None] = {
            "healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 2) if self.latency_ms is not None else None,
        }
        if include_detail:
            payload["detail"] = self.detail
        return payload


type ReadinessCheck = Callable[
    [FastAPI],
    ReadinessCheckResult | Awaitable["ReadinessCheckResult"],
]


class ReadinessRegistry:
    """Registry of dependency checks contributing to readiness."""

    def __init__(self) -> None:
        self._checks: dict[str, ReadinessCheck] = {}

    def register(self, name: str, check: ReadinessCheck) -> None:
        """Register or replace a named readiness check."""
        self._checks[name] = check

    async def run(self, app: FastAPI) -> list[ReadinessCheckResult]:
        """
        Execute all registered readiness checks sequentially.

        The registry accepts both synchronous and asynchronous checks so simple
        in-process probes do not need artificial `async` wrappers.
        """
        results: list[ReadinessCheckResult] = []
        for check in self._checks.values():
            start = perf_counter()
            maybe_result = check(app)
            result = await maybe_result if isawaitable(maybe_result) else maybe_result
            if result.latency_ms is None:
                result.latency_ms = (perf_counter() - start) * 1000
            results.append(result)
        return results
