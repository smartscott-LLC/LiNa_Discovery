"""LINA telemetry — lightweight, dependency-free Prometheus exposition.

Counters are plain process-global integers; the /metrics endpoint renders
them in Prometheus text format. No external metrics agent is required —
`METRICS_ENABLED=1` turns the endpoint on.
"""

from __future__ import annotations

import time
from collections import Counter

_STARTED_AT = time.monotonic()

_COUNTERS: dict[str, Counter] = {
    "lina_requests_total": Counter(),
    "lina_evaluations_total": Counter(),
    "lina_corrections_total": Counter(),
    "lina_season_advances_total": Counter(),
    "lina_voice_fallbacks_total": Counter(),
    "lina_bridge_messages_total": Counter(),
}

_GAUGES: dict[str, float] = {}


def _label_key(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def inc(family: str, labels: dict[str, str] | None = None) -> None:
    """Increment a counter family (optionally labeled)."""
    counter = _COUNTERS.get(family)
    if counter is not None:
        counter[_label_key(labels)] += 1


def set_gauge(name: str, value: float) -> None:
    _GAUGES[name] = value


def uptime_seconds() -> float:
    return time.monotonic() - _STARTED_AT


def render() -> str:
    """Render all metrics in Prometheus text exposition format."""
    lines: list[str] = []
    for family, counter in _COUNTERS.items():
        for label_key, value in sorted(counter.items()):
            label_suffix = f"{{{label_key}}}" if label_key else ""
            lines.append(f"{family}{label_suffix} {value}")
    for name, value in sorted(_GAUGES.items()):
        lines.append(f"{name} {value}")
    lines.append(f"lina_uptime_seconds {uptime_seconds():.3f}")
    lines.append("# EOF")
    return "\n".join(lines) + "\n"
