"""Metrics (Docs_COMPLEX/observability/METRICS.md) — Prometheus, one registry.

The doc's core series: LLM calls/latency/tokens per role, tool executions per
tier/outcome, agent turns, ingest counts. Exposed at GET /metrics.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

LLM_CALLS = Counter(
    "alan_llm_calls_total", "LLM calls by role/model/outcome",
    ["role", "model", "outcome"], registry=REGISTRY)
LLM_LATENCY = Histogram(
    "alan_llm_latency_seconds", "LLM call latency by role", ["role"], registry=REGISTRY)
LLM_TOKENS = Counter(
    "alan_llm_tokens_total", "LLM tokens by role/direction", ["role", "direction"],
    registry=REGISTRY)
TOOL_EXECUTIONS = Counter(
    "alan_tool_executions_total", "Tool executions by tool/tier/outcome",
    ["tool", "tier", "outcome"], registry=REGISTRY)
AGENT_TURNS = Counter(
    "alan_agent_turns_total", "Agent turns by agent/status", ["agent", "status"],
    registry=REGISTRY)
TASK_RUNS = Counter(
    "alan_task_runs_total", "Planner task runs by outcome", ["outcome"], registry=REGISTRY)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
