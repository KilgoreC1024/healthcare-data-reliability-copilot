"""Per-token prices (USD per million tokens) used for cost accounting.

First-party Claude API list prices as published in October 2026. Cache writes use the 5-minute TTL rate
(1.25x input). Update this table when prices change; evaluation results record the model so historical
costs can be recomputed.
"""

from __future__ import annotations

from drc.models import Usage

PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
}


def cost(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens * price["input"]
        + output_tokens * price["output"]
        + cache_read * price["cache_read"]
        + cache_write * price["cache_write"]
    ) / 1_000_000


def add_usage(total: Usage, model: str, usage: object) -> None:
    """Accumulate one API response's usage (the SDK's `response.usage`) into `total`."""
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    total.input_tokens += inp
    total.output_tokens += out
    total.cache_read_tokens += read
    total.cache_write_tokens += write
    total.cost_usd = round(total.cost_usd + cost(model, inp, out, read, write), 6)
    total.turns += 1
