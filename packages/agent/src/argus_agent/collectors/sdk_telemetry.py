"""Virtual collector that analyzes SDK telemetry data streams."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from argus_agent.events.bus import get_event_bus
from argus_agent.events.types import Event, EventSeverity, EventSource, EventType

if TYPE_CHECKING:
    from argus_agent.baseline.anomaly import AnomalyDetector

logger = logging.getLogger("argus.collectors.sdk_telemetry")


class SDKTelemetryCollector:
    """Periodically analyzes SDK event data and emits alerts.

    Detects:
    - Error rate spikes
    - Latency degradation
    - Cold start regression
    - Services going silent
    - SDK runtime metric anomalies (when anomaly detector is set)
    """

    def __init__(self, interval: int = 60) -> None:
        self._interval = interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # Track previous analysis for comparison
        self._prev_error_rates: dict[str, float] = {}
        self._prev_p95_latency: dict[str, float] = {}
        self._prev_cold_start_pct: dict[str, float] = {}
        self._known_services: set[str] = set()
        self._anomaly_detector: AnomalyDetector | None = None

    @property
    def anomaly_detector(self) -> AnomalyDetector | None:
        return self._anomaly_detector

    @anomaly_detector.setter
    def anomaly_detector(self, detector: AnomalyDetector) -> None:
        self._anomaly_detector = detector

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._analyze_loop())
        logger.info("SDK telemetry collector started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SDK telemetry collector stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _analyze_loop(self) -> None:
        while self._running:
            try:
                await self._analyze()
            except Exception:
                logger.exception("SDK telemetry analysis error")
            await asyncio.sleep(self._interval)

    async def _analyze(self) -> None:
        """Run a single analysis pass over recent SDK data."""
        try:
            from argus_agent.storage.timeseries import (
                query_function_metrics,
                query_service_summary,
            )
        except RuntimeError:
            return  # Storage not initialized

        bus = get_event_bus()

        # Get service summaries
        try:
            summaries = query_service_summary(since_minutes=5)
        except Exception:
            return

        current_services = {s["service"] for s in summaries}

        # Detect services that went silent
        for svc in self._known_services - current_services:
            if svc in self._known_services:
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_SERVICE_SILENT,
                    severity=EventSeverity.NOTABLE,
                    message=f"Service '{svc}' has stopped sending telemetry",
                    data={"service": svc},
                ))

        self._known_services = current_services

        # Analyze each service
        for summary in summaries:
            svc = summary["service"]
            if summary["invocation_count"] == 0:
                continue

            try:
                buckets = query_function_metrics(
                    service=svc, since_minutes=5, interval_minutes=5,
                )
            except Exception:
                continue

            if not buckets:
                continue

            latest = buckets[-1]
            error_rate = latest.get("error_rate", 0)
            p95 = latest.get("p95_duration_ms", 0)
            cold_start_pct = latest.get("cold_start_pct", 0)

            # Error rate spike detection
            prev_error_rate = self._prev_error_rates.get(svc, 0)
            if error_rate > 10 and error_rate > prev_error_rate * 2:
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_ERROR_SPIKE,
                    severity=EventSeverity.URGENT,
                    message=(
                        f"Error rate spike in '{svc}': "
                        f"{error_rate:.1f}% (was {prev_error_rate:.1f}%)"
                    ),
                    data={"service": svc, "error_rate": error_rate,
                          "previous_error_rate": prev_error_rate},
                ))
            self._prev_error_rates[svc] = error_rate

            # Latency degradation
            prev_p95 = self._prev_p95_latency.get(svc, 0)
            if p95 > 1000 and prev_p95 > 0 and p95 > prev_p95 * 2:
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_LATENCY_DEGRADATION,
                    severity=EventSeverity.NOTABLE,
                    message=(
                        f"Latency spike in '{svc}': "
                        f"p95={p95:.0f}ms (was {prev_p95:.0f}ms)"
                    ),
                    data={"service": svc, "p95_ms": p95, "previous_p95_ms": prev_p95},
                ))
            self._prev_p95_latency[svc] = p95

            # Cold start regression
            prev_cold = self._prev_cold_start_pct.get(svc, 0)
            if cold_start_pct > 30 and cold_start_pct > prev_cold * 2:
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_COLD_START_SPIKE,
                    severity=EventSeverity.NOTABLE,
                    message=(
                        f"Cold start spike in '{svc}': "
                        f"{cold_start_pct:.1f}% (was {prev_cold:.1f}%)"
                    ),
                    data={"service": svc, "cold_start_pct": cold_start_pct,
                          "previous_cold_start_pct": prev_cold},
                ))
            self._prev_cold_start_pct[svc] = cold_start_pct

        # Check SDK runtime metrics against baselines
        await self._check_sdk_metric_anomalies(bus)

    async def _check_sdk_metric_anomalies(self, bus: object) -> None:
        """Check recent SDK runtime metrics against baselines."""
        if self._anomaly_detector is None:
            return

        try:
            from argus_agent.storage.timeseries import query_sdk_metrics
        except RuntimeError:
            return

        # Get the latest SDK metrics (last 2 minutes)
        try:
            recent = query_sdk_metrics(since_minutes=2, limit=200)
        except Exception:
            return

        for entry in recent:
            svc = entry["service"]
            metric_name = entry["metric_name"]
            value = entry["value"]

            # Check against baseline using sdk.{service}.{metric_name} naming
            baseline_key = f"sdk.{svc}.{metric_name}"
            anomaly = self._anomaly_detector.check_metric(baseline_key, value)
            if anomaly:
                await bus.publish(Event(
                    source=EventSource.SDK_TELEMETRY,
                    type=EventType.SDK_METRIC_ANOMALY,
                    severity=anomaly.severity,
                    message=anomaly.message,
                    data={
                        "service": svc,
                        "metric_name": metric_name,
                        "value": value,
                        "z_score": anomaly.z_score,
                    },
                ))
