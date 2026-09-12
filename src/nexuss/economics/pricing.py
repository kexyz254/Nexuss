"""Centralized versioned AI pricing and provider-usage accounting.

P6.14 — AI Usage Economics.

This module is the single source of truth for provider pricing. Pricing is
versioned so that historical cost calculations remain immutable even when
pricing data is later updated. Costs are always computed in UTC using the
pricing band that was authoritative at the time of the call.

Never fabricate unavailable cost or usage. When authoritative token data is
absent, the corresponding fields remain ``None`` and no cost is derived from
them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Optional

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Pricing primitives
# ---------------------------------------------------------------------------

# Prices are expressed in USD per million (1_000_000) tokens.
_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class PricingBand:
    """A single pricing band for a provider model."""

    cache_hit_per_million: Decimal
    cache_miss_per_million: Decimal
    output_per_million: Decimal


@dataclass(frozen=True)
class PeakWindow:
    """A recurring UTC peak-pricing window."""

    start_hour: int
    end_hour: int  # exclusive
    weekdays: frozenset[int]  # 0=Monday .. 6=Sunday


@dataclass(frozen=True)
class ModelPricing:
    """Versioned pricing for one provider model."""

    provider: str
    model: str
    version: int
    off_peak: PricingBand
    peak: PricingBand
    peak_windows: tuple[PeakWindow, ...] = ()

    def is_peak(self, when: datetime) -> bool:
        """Return True if ``when`` (UTC) falls inside a peak window."""
        utc = when.astimezone(UTC)
        weekday = utc.weekday()
        hour = utc.hour
        for window in self.peak_windows:
            if weekday not in window.weekdays:
                continue
            if window.start_hour <= hour < window.end_hour:
                return True
        return False

    def band_for(self, when: datetime) -> PricingBand:
        return self.peak if self.is_peak(when) else self.off_peak


# ---------------------------------------------------------------------------
# Seed data: DeepSeek V4 Pro
# ---------------------------------------------------------------------------

# Off-peak: cache hit $0.022/M, cache miss $0.66/M, output $1.98/M.
# Peak:     cache hit $0.044/M, cache miss $1.32/M, output $3.96/M.
# Peak periods: 01:00-04:00 UTC and 06:00-10:00 UTC Monday-Friday.
DEEPSEEK_V4_PRO = ModelPricing(
    provider="deepseek",
    model="deepseek-v4-pro",
    version=1,
    off_peak=PricingBand(
        cache_hit_per_million=Decimal("0.022"),
        cache_miss_per_million=Decimal("0.66"),
        output_per_million=Decimal("1.98"),
    ),
    peak=PricingBand(
        cache_hit_per_million=Decimal("0.044"),
        cache_miss_per_million=Decimal("1.32"),
        output_per_million=Decimal("3.96"),
    ),
    peak_windows=(
        PeakWindow(start_hour=1, end_hour=4, weekdays=frozenset({0, 1, 2, 3, 4})),
        PeakWindow(start_hour=6, end_hour=10, weekdays=frozenset({0, 1, 2, 3, 4})),
    ),
)

# Versioned registry. New pricing versions are appended; historical versions
# are retained so past costs remain immutable.
PRICING_REGISTRY: Mapping[str, tuple[ModelPricing, ...]] = {
    "deepseek/deepseek-v4-pro": (DEEPSEEK_V4_PRO,),
}


def get_pricing(provider: str, model: str, version: Optional[int] = None) -> ModelPricing:
    """Return the pricing record for a provider/model.

    If ``version`` is None, the latest version is returned. If a specific
    version is requested, the exact historical record is returned so that
    past costs can be recomputed deterministically.
    """
    key = f"{provider}/{model}"
    versions = PRICING_REGISTRY.get(key)
    if not versions:
        raise KeyError(f"No pricing registered for {key}")
    if version is None:
        return versions[-1]
    for record in versions:
        if record.version == version:
            return record
    raise KeyError(f"No pricing version {version} for {key}")


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    """Authoritative token usage for a single provider call.

    All fields are optional. A field is ``None`` when the provider did not
    return authoritative data for it. We never fabricate values.
    """

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_hit_tokens: Optional[int] = None
    cache_miss_tokens: Optional[int] = None

    @property
    def total_tokens(self) -> Optional[int]:
        parts = [
            v
            for v in (
                self.input_tokens,
                self.output_tokens,
                self.cache_hit_tokens,
                self.cache_miss_tokens,
            )
            if v is not None
        ]
        if not parts:
            return None
        return sum(parts)


@dataclass(frozen=True)
class CostBreakdown:
    """Immutable cost breakdown for a single call."""

    cache_hit_cost: Decimal = Decimal("0")
    cache_miss_cost: Decimal = Decimal("0")
    output_cost: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.cache_hit_cost + self.cache_miss_cost + self.output_cost


def _per_million_cost(tokens: Optional[int], per_million: Decimal) -> Decimal:
    if tokens is None or tokens <= 0:
        return Decimal("0")
    return (Decimal(tokens) / _PER_MILLION * per_million).quantize(
        Decimal("0.00000001"), rounding=ROUND_HALF_UP
    )


def calculate_cost(
    usage: TokenUsage,
    pricing: ModelPricing,
    when: datetime,
) -> CostBreakdown:
    """Calculate an immutable cost using the UTC pricing band for ``when``.

    Only authoritative token counts contribute to cost. Missing counts are
    treated as zero and never estimated here (estimation is a separate,
    explicitly-labelled path).
    """
    band = pricing.band_for(when)
    return CostBreakdown(
        cache_hit_cost=_per_million_cost(usage.cache_hit_tokens, band.cache_hit_per_million),
        cache_miss_cost=_per_million_cost(usage.cache_miss_tokens, band.cache_miss_per_million),
        output_cost=_per_million_cost(usage.output_tokens, band.output_per_million),
    )


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: ModelPricing,
    when: datetime,
    cache_hit_ratio: Decimal = Decimal("0"),
) -> CostBreakdown:
    """Deterministic preflight estimate.

    This is explicitly an *estimate*: it assumes all input tokens are cache
    misses unless ``cache_hit_ratio`` is supplied, and it assumes the given
    output token count. It is never recorded as actual cost.
    """
    band = pricing.band_for(when)
    cache_hit = int(Decimal(input_tokens) * cache_hit_ratio)
    cache_miss = input_tokens - cache_hit
    return CostBreakdown(
        cache_hit_cost=_per_million_cost(cache_hit, band.cache_hit_per_million),
        cache_miss_cost=_per_million_cost(cache_miss, band.cache_miss_per_million),
        output_cost=_per_million_cost(output_tokens, band.output_per_million),
    )
