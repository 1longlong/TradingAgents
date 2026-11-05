"""Run request schema. Unknown fields are rejected on purpose."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    trade_date: str = Field(min_length=10, max_length=10)
    asset_type: Literal["stock", "crypto"] = "stock"
    output_language: str = "English"
    analysts: list[str] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: int = 1
    llm_provider: str = "openai"
    backend_url: str | None = None
    quick_think_llm: str | None = None
    deep_think_llm: str | None = None
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    checkpoint: bool = False
    portfolio_json: str | None = None


class PortfolioValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    json_text: str = Field(alias="json")


class CheckpointClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str
