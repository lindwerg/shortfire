"""Coinglass v4 response schemas.

D-52: Pydantic v2 strict validation at the Coinglass→data-platform boundary.
Pitfall G: `extra='allow'` tolerates Coinglass field renames/additions without breaking ingest.
D-59: source attribution always 'coinglass_aggregate' (or 'coinglass_mexc_only' deferred to Phase 2).
D-54: 1m candle backfill capped at ~6 days (Hobbyist tier); granularity_seconds reserved for Phase 2.

Four top-level response schemas (one per endpoint):
  FundingRateListResponse       — /api/futures/funding-rate-list (batch, all symbols at once)
  OpenInterestHistoryResponse   — /api/futures/open-interest/history (per-symbol)
  LiquidationCoinHistoryResponse — /api/futures/liquidation/coin-history (per-symbol)
  LongShortAccountRatioResponse — /api/futures/long-short-account-ratio (per-symbol)

All schemas have:
  - model_config = ConfigDict(frozen=True, strict=True, extra='allow')
  - to_record() or to_records() returning tuples ready for copy_into_hypertable

Symbol note: Coinglass returns bare-coin symbols ("BTC", "ETH").
The caller in funding_agg.py maps to unified format ("BTC/USDT:USDT") before INSERT.
Schemas store the wire value; mapping is the caller's responsibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# FundingRateListResponse — /api/futures/funding-rate-list
# ---------------------------------------------------------------------------


class FundingRateListRow(BaseModel):
    """Single row in the Coinglass funding-rate-list batch response.

    symbol: Coinglass bare-coin identifier ("BTC") — caller maps to unified.
    funding_rate: Can be None for illiquid symbols; caller skips None rows before INSERT.
    next_funding_time: Unix ms timestamp; informational only in Phase 1.
    """

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    symbol: str
    funding_rate: Decimal | None = None
    next_funding_time: int | None = None

    def to_record(self, source: str = "coinglass_aggregate") -> tuple[str, None, Decimal | None, str, str]:
        """Build a 5-tuple for copy_into_hypertable into raw_coinglass_funding_agg.

        Columns: (symbol, ts, funding_rate, source, quality_flag)
        Note: ts is set to None here; the caller (funding_agg.py) injects datetime.now(UTC).
        D-59: source is always 'coinglass_aggregate' regardless of wire payload content.
        """
        return (self.symbol, None, self.funding_rate, "coinglass_aggregate", "ok")


class FundingRateListResponse(BaseModel):
    """Top-level Coinglass /api/futures/funding-rate-list response.

    code: Coinglass status code (0 = success).
    msg: Human-readable status message.
    data: Tuple of FundingRateListRow — all active symbols in one batch call.
    """

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    code: int
    msg: str
    data: tuple[FundingRateListRow, ...] = ()


# ---------------------------------------------------------------------------
# OpenInterestHistoryResponse — /api/futures/open-interest/history
# ---------------------------------------------------------------------------


class OpenInterestHistoryRow(BaseModel):
    """Single OI data point from Coinglass per-symbol history endpoint."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    time: int  # Unix ms timestamp
    open_interest_usd: Decimal | None = None


class OpenInterestHistoryResponse(BaseModel):
    """Top-level Coinglass /api/futures/open-interest/history response."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    code: int = 0
    msg: str = ""
    data: tuple[OpenInterestHistoryRow, ...] = ()

    def to_records(
        self,
        symbol_unified: str,
        source: str = "coinglass_aggregate",
    ) -> list[tuple[str, datetime, Decimal | None, str, str]]:
        """Convert to list of tuples for copy_into_hypertable into raw_coinglass_oi.

        Columns: (symbol, ts, open_interest, source, quality_flag)
        D-59: source forced to 'coinglass_aggregate'.
        """
        # WR-01: raw_coinglass_oi.open_interest is NOT NULL in migration 0009.
        # Replace None with Decimal("0") so we never pass NULL to a NOT NULL column.
        # Coinglass occasionally omits open_interest_usd for illiquid symbols; Decimal("0")
        # is the correct sentinel value for "no open interest reported this interval".
        return [
            (
                symbol_unified,
                datetime.fromtimestamp(row.time / 1000, tz=UTC),
                row.open_interest_usd if row.open_interest_usd is not None else Decimal("0"),
                "coinglass_aggregate",
                "ok",
            )
            for row in self.data
        ]


# ---------------------------------------------------------------------------
# LiquidationCoinHistoryResponse — /api/futures/liquidation/coin-history
# ---------------------------------------------------------------------------


class LiquidationCoinHistoryRow(BaseModel):
    """Single liquidation data point — has separate long and short USD amounts."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    time: int  # Unix ms timestamp
    liquidation_long_usd: Decimal | None = None
    liquidation_short_usd: Decimal | None = None


class LiquidationCoinHistoryResponse(BaseModel):
    """Top-level Coinglass /api/futures/liquidation/coin-history response."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    code: int = 0
    msg: str = ""
    data: tuple[LiquidationCoinHistoryRow, ...] = ()

    def to_records(
        self,
        symbol_unified: str,
        source: str = "coinglass_aggregate",
    ) -> list[tuple[str, datetime, str, Decimal, str, str]]:
        """Convert to list of tuples for copy_into_hypertable into raw_coinglass_liq.

        Each data point produces TWO records — one per side (long + short).
        Columns: (symbol, ts, side, liquidation_usd, source, quality_flag)
        D-59: source forced to 'coinglass_aggregate'.
        WR-01: liquidation_usd is always Decimal (never None) — None → Decimal("0").
        """
        # WR-01: raw_coinglass_liq.liquidation_usd is NOT NULL in migration 0009.
        # Replace None with Decimal("0") for both long and short sides.
        records: list[tuple[str, datetime, str, Decimal, str, str]] = []
        for row in self.data:
            ts = datetime.fromtimestamp(row.time / 1000, tz=UTC)
            liq_long = row.liquidation_long_usd if row.liquidation_long_usd is not None else Decimal("0")
            liq_short = row.liquidation_short_usd if row.liquidation_short_usd is not None else Decimal("0")
            records.append((symbol_unified, ts, "long", liq_long, "coinglass_aggregate", "ok"))
            records.append((symbol_unified, ts, "short", liq_short, "coinglass_aggregate", "ok"))
        return records


# ---------------------------------------------------------------------------
# LongShortAccountRatioResponse — /api/futures/long-short-account-ratio
# ---------------------------------------------------------------------------


class LongShortAccountRatioRow(BaseModel):
    """Single long/short ratio data point from Coinglass."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    time: int  # Unix ms timestamp
    long_short_ratio: Decimal | None = None


class LongShortAccountRatioResponse(BaseModel):
    """Top-level Coinglass /api/futures/long-short-account-ratio response."""

    model_config = ConfigDict(frozen=True, strict=False, extra="allow")

    code: int = 0
    msg: str = ""
    data: tuple[LongShortAccountRatioRow, ...] = ()

    def to_records(
        self,
        symbol_unified: str,
        source: str = "coinglass_aggregate",
    ) -> list[tuple[str, datetime, Decimal | None, str, str]]:
        """Convert to list of tuples for copy_into_hypertable into raw_coinglass_lsr.

        Columns: (symbol, ts, long_short_ratio, source, quality_flag)
        D-59: source forced to 'coinglass_aggregate'.
        """
        return [
            (
                symbol_unified,
                datetime.fromtimestamp(row.time / 1000, tz=UTC),
                row.long_short_ratio,
                "coinglass_aggregate",
                "ok",
            )
            for row in self.data
        ]
