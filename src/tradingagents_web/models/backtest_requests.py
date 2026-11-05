"""Backtest request schema. Unknown fields are rejected on purpose."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(min_length=1)
    start: str = Field(min_length=10, max_length=10)
    end: str = Field(min_length=10, max_length=10)
    every: int = Field(default=7, ge=1)
    analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    asset_type: Literal["stock", "crypto"] = "stock"
    portfolio_json: str | None = None
    run_id: str | None = None
