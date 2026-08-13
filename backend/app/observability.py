"""Privacy-safe OpenTelemetry setup for the greenfield runtime.

The application owns the instrumentation boundary, while the collector and
telemetry backend remain deployment choices.  Local and test environments use
the OpenTelemetry no-op API by default; production must explicitly configure
an OTLP/HTTP collector endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from urllib.parse import urlparse

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Tracer

from backend.app.config import Settings


logger = logging.getLogger("aineta.observability")


class TelemetryConfigurationError(ValueError):
    """Raised when enabled telemetry cannot be configured safely."""


def _collector_endpoint(base_endpoint: str, signal: str) -> str:
    """Build an OTLP/HTTP signal endpoint without accepting arbitrary paths."""

    parsed = urlparse(base_endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TelemetryConfigurationError(
            "OTEL_EXPORTER_OTLP_ENDPOINT must be an absolute HTTP(S) URL"
        )
    if parsed.params or parsed.query or parsed.fragment:
        raise TelemetryConfigurationError(
            "OTEL_EXPORTER_OTLP_ENDPOINT must not contain params, query, or fragment"
        )
    path = parsed.path.rstrip("/")
    if path.endswith(f"/v1/{signal}"):
        return base_endpoint.rstrip("/")
    if path:
        raise TelemetryConfigurationError(
            "OTEL_EXPORTER_OTLP_ENDPOINT must be a collector base URL"
        )
    return f"{base_endpoint.rstrip('/')}/v1/{signal}"


@dataclass(slots=True)
class Telemetry:
    """Application-owned tracer and low-cardinality HTTP instruments."""

    enabled: bool
    tracer: Tracer
    meter: Meter
    request_count: Counter
    request_duration: Histogram
    _tracer_provider: TracerProvider | None = field(default=None, repr=False)
    _meter_provider: MeterProvider | None = field(default=None, repr=False)

    @classmethod
    def disabled(cls) -> "Telemetry":
        meter = metrics.get_meter("ai-neta")
        return cls(
            enabled=False,
            tracer=trace.get_tracer("ai-neta"),
            meter=meter,
            request_count=meter.create_counter(
                "aineta.http.request.count", unit="{request}"
            ),
            request_duration=meter.create_histogram(
                "aineta.http.request.duration", unit="s"
            ),
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        span_exporter: SpanExporter | None = None,
        metric_reader: MetricReader | None = None,
    ) -> "Telemetry":
        """Build telemetry without making a network call during app creation."""

        if not settings.otel_enabled:
            return cls.disabled()
        if settings.otel_exporter != "otlp_http" and span_exporter is None:
            raise TelemetryConfigurationError(
                "OTEL_EXPORTER=otlp_http is required when telemetry is enabled"
            )

        resource = Resource.create(
            {
                SERVICE_NAME: settings.service_name,
                SERVICE_VERSION: "0.1.0",
                "deployment.environment.name": settings.environment,
            }
        )
        tracer_provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(settings.otel_sample_ratio),
        )
        if span_exporter is None:
            span_exporter = OTLPSpanExporter(
                endpoint=_collector_endpoint(settings.otel_exporter_endpoint, "traces")
            )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(span_exporter, max_queue_size=2048)
            )
        else:
            tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

        if metric_reader is None and settings.otel_exporter == "otlp_http":
            metric_reader = PeriodicMetricReaderFactory.create(
                _collector_endpoint(settings.otel_exporter_endpoint, "metrics")
            )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader] if metric_reader else [])
        tracer = tracer_provider.get_tracer("ai-neta")
        meter = meter_provider.get_meter("ai-neta")
        return cls(
            enabled=True,
            tracer=tracer,
            meter=meter,
            request_count=meter.create_counter(
                "aineta.http.request.count", unit="{request}"
            ),
            request_duration=meter.create_histogram(
                "aineta.http.request.duration", unit="s"
            ),
            _tracer_provider=tracer_provider,
            _meter_provider=meter_provider,
        )

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record only bounded route/status dimensions; never body or URL values."""

        attributes: dict[str, str | int] = {
            "http.request.method": method,
            "http.route": route,
            "http.response.status_code": status_code,
        }
        self.request_count.add(1, attributes)
        self.request_duration.record(duration_seconds, attributes)

    def shutdown(self) -> None:
        """Flush providers during graceful shutdown without leaking telemetry errors."""

        for provider in (self._tracer_provider, self._meter_provider):
            if provider is None:
                continue
            try:
                provider.shutdown()
            except Exception as exc:  # pragma: no cover - provider-specific failure
                logger.warning(
                    "telemetry_provider_shutdown_failed",
                    extra={"provider_type": type(provider).__name__, "error_type": type(exc).__name__},
                )


class PeriodicMetricReaderFactory:
    """Lazy factory kept separate so tests can inject an in-memory reader."""

    @staticmethod
    def create(endpoint: str) -> MetricReader:
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        return PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint),
            export_interval_millis=60_000,
        )
