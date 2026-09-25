# Observability

Jurix exposes Prometheus metrics and optional OpenTelemetry traces. Metrics work without a tracing backend.

Set `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` to export HTTP, RAG retrieval and RAG generation spans. HTTP spans carry the same correlation ID emitted as `X-Request-ID`.
