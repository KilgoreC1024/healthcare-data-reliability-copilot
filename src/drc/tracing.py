"""Investigation tracing in the OpenTelemetry span model, written as JSON lines.

Spans use OpenTelemetry field names and the GenAI semantic-convention attribute names
(`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.tool.name`, ...), so a trace file can be
replayed into any OTLP backend. Exporting directly over OTLP is on the roadmap; keeping the dependency
out of the core package means investigations run anywhere, including CI.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Span:
    def __init__(self, tracer: Tracer, name: str, parent: str | None, attributes: dict[str, Any]):
        self.tracer = tracer
        self.name = name
        self.span_id = secrets.token_hex(8)
        self.parent = parent
        self.attributes = dict(attributes)
        self.start = time.time_ns()
        self.end: int | None = None
        self.status = "OK"

    def set(self, **attributes: Any) -> None:
        self.attributes.update(attributes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "traceId": self.tracer.trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent,
            "name": self.name,
            "startTimeUnixNano": self.start,
            "endTimeUnixNano": self.end,
            "status": self.status,
            "attributes": self.attributes,
        }


class Tracer:
    def __init__(self, path: Path | None = None, trace_id: str | None = None):
        self.trace_id = trace_id or secrets.token_hex(16)
        self.path = path
        self.spans: list[Span] = []
        self._stack: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        span = Span(self, name, self._stack[-1].span_id if self._stack else None, attributes)
        self._stack.append(span)
        try:
            yield span
        except Exception as exc:
            span.status = "ERROR"
            span.set(**{"exception.type": type(exc).__name__, "exception.message": str(exc)[:500]})
            raise
        finally:
            span.end = time.time_ns()
            self._stack.pop()
            self.spans.append(span)

    def flush(self) -> Path | None:
        if self.path is None:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for span in sorted(self.spans, key=lambda s: s.start):
                handle.write(json.dumps(span.to_dict(), default=str) + "\n")
        return self.path
