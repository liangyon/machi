"""In-memory metrics and recent-job snapshots (single-instance baseline)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from threading import Lock


@dataclass
class RecommendationJobSnapshot:
    job_id: str
    user_id: str
    status: str
    stage: str
    duration_ms: int | None
    used_fallback: bool
    error_code: str | None
    error: str | None


_lock = Lock()
_counters: dict[str, float] = {
    "recommendation_total": 0,
    "recommendation_success": 0,
    "recommendation_failed": 0,
    "recommendation_fallback": 0,
    "error_VALIDATION_ERROR": 0,
    "error_INTERNAL_ERROR": 0,
    "error_UPSTREAM_TIMEOUT": 0,
    "error_LLM_BUDGET_EXCEEDED": 0,
    "llm_tokens_prompt": 0,
    "llm_tokens_completion": 0,
    "llm_estimated_cost_usd": 0.0,
}
_latencies_ms: deque[int] = deque(maxlen=500)
_recent_jobs: deque[RecommendationJobSnapshot] = deque(maxlen=100)


def increment(name: str, value: float = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + value


def observe_latency(ms: int) -> None:
    with _lock:
        _latencies_ms.append(ms)


def record_llm_usage(*, prompt_tokens: int, completion_tokens: int, estimated_cost_usd: float) -> None:
    with _lock:
        _counters["llm_tokens_prompt"] = _counters.get("llm_tokens_prompt", 0) + prompt_tokens
        _counters["llm_tokens_completion"] = _counters.get("llm_tokens_completion", 0) + completion_tokens
        _counters["llm_estimated_cost_usd"] = _counters.get("llm_estimated_cost_usd", 0.0) + estimated_cost_usd


def record_recent_job(snapshot: RecommendationJobSnapshot) -> None:
    with _lock:
        _recent_jobs.appendleft(snapshot)


def get_metrics_summary() -> dict:
    with _lock:
        latencies = list(_latencies_ms)
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        fallback_rate = 0.0
        total = _counters.get("recommendation_total", 0)
        if total:
            fallback_rate = round(_counters.get("recommendation_fallback", 0) / total, 4)

        return {
            "counters": dict(_counters),
            "latency": {
                "samples": len(latencies),
                "avg_ms": avg_latency,
                "latest_ms": latencies[0] if latencies else None,
            },
            "fallback_rate": fallback_rate,
        }


def get_recent_jobs(limit: int = 20) -> list[dict]:
    with _lock:
        return [asdict(j) for j in list(_recent_jobs)[:limit]]
